"""Fixed previous/current/next prompts and music-clock timers.

The body changes only at cue boundaries. Small transparent timer strips change
independently, so an hour-long export does not need thousands of full frames.
"""
from bisect import bisect_right
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
import math

from studio import FONT, ValidationError, wrap_text


ELAPSED_COLOR = "#00ba38"
REMAINING_COLOR = "#ff3030"
ACCENT_COLOR = "#ffff00"


def palette(style):
    rgb = [int(style["background"][i:i + 2], 16) for i in (1, 3, 5)]
    if sum(value * weight for value, weight in zip(rgb, (.2126, .7152, .0722))) > 150:
        return "#007b2b", "#c71d27", "#806600"
    return ELAPSED_COLOR, REMAINING_COLOR, ACCENT_COLOR


def clock(milliseconds, ceil=False):
    seconds = max(0, math.ceil(milliseconds / 1000) if ceil else math.floor(milliseconds / 1000))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return (f"{hours:02}:" if hours else "") + f"{minutes:02}:{seconds:02}"


def snapshot(project, at_ms, duration_ms):
    duration_ms = max(1, int(duration_ms))
    at_ms = max(0, min(duration_ms, int(at_ms)))
    cues, offset = project["segments"], project.get("cueOffsetMs", 0)
    shifted = at_ms - offset
    before = bisect_right([cue["startMs"] for cue in cues], shifted) - 1
    current = before if at_ms < duration_ms and before >= 0 and cues[before]["endMs"] > shifted else -1
    previous = current - 1 if current >= 0 else before
    following = current + 1 if current >= 0 else before + 1
    upcoming = following if following < len(cues) else -1
    if current >= 0:
        target, label = min(duration_ms, cues[current]["endMs"] + offset), "DO KONCA TEXTU"
    elif upcoming >= 0:
        target, label = cues[upcoming]["startMs"] + offset, "ĎALŠÍ TEXT O"
    else:
        target, label = duration_ms, "DO KONCA HUDBY"
    return {"previous": previous, "current": current, "next": upcoming,
            "elapsed": clock(at_ms), "remaining": clock(duration_ms - at_ms, ceil=True),
            "countdown": max(0, math.ceil((target - at_ms) / 1000)), "countdownLabel": label,
            "targetMs": target}


@lru_cache(maxsize=256)
def font(size, bold=False):
    result = ImageFont.truetype(str(FONT), size=max(1, size))
    if bold:
        result.set_variation_by_name("SemiBold")
    return result


def secondary_color(style):
    def rgb(value):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    foreground, background = rgb(style["color"]), rgb(style["background"])
    return tuple(round(a * .56 + b * .44) for a, b in zip(foreground, background))


def draw_box(draw, text, box, size, color, bold=False):
    if not text:
        return
    left, top, width, height = box
    minimum = 14
    size = max(minimum, int(size))
    while True:
        face = font(size, bold)
        lines = wrap_text(draw, text, face, width)
        line_height = round(size * 1.3)
        if len(lines) * line_height <= height:
            break
        if size <= minimum:
            raise ValidationError("A teleprompter prompt is too long for its area. Split that cue before exporting.")
        size -= 1
    y = top + (height - len(lines) * line_height) / 2
    for index, line in enumerate(lines):
        draw.text((left + width / 2, y + index * line_height), line, font=face, fill=color, anchor="mt")


def make_body(project, state):
    style, cues = project["style"], project["segments"]
    width, height = style["width"], style["height"]
    scale = width / 1920
    image = Image.new("RGB", (width, height), style["background"])
    draw = ImageDraw.Draw(image)
    muted = secondary_color(style)
    green, red, yellow = palette(style)
    label = font(round(18 * scale), True)
    draw.text((width * .07, height * .025), "UPLYNULO", font=label, fill=green, anchor="lt")
    draw.text((width * .93, height * .025), "DO KONCA", font=label, fill=red, anchor="rt")
    draw_box(draw, project.get("name", ""), (width * .29, height * .025, width * .42, height * .1), round(29 * scale), yellow, True)
    zones = (("previous", .19, .22, .12, "PREDCHÁDZAJÚCI TEXT"),
             ("current", .375, .405, .26, "TERAZ"),
             ("next", .72, .75, .13, "NASLEDUJÚCI TEXT"))
    for key, label_y, top, area_height, caption in zones:
        index = state[key]
        if index < 0:
            if key == "current":
                draw.text((width / 2, height * .51), "PAUZA", font=font(round(27 * scale)), fill=muted, anchor="mt")
            continue
        active = key == "current"
        draw.text((width / 2, height * label_y), caption, font=label, fill=yellow if active else muted, anchor="mt")
        size = round(style["fontSize"] * scale * (1 if active else .64))
        draw_box(draw, cues[index]["text"], (width * .07, height * top, width * .86, height * area_height), size,
                 style["color"] if active else muted, active)
    return image


def make_clocks(project, state):
    style = project["style"]
    width, height = style["width"], style["height"]
    image = Image.new("RGBA", (width, math.ceil(height * .16)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    face = font(round(65 * width / 1920), True)
    green, red, _ = palette(style)
    draw.text((width * .07, height * .06), state["elapsed"], font=face, fill=green, anchor="lt")
    draw.text((width * .93, height * .06), state["remaining"], font=face, fill=red, anchor="rt")
    return image


def make_countdown(project, state):
    style = project["style"]
    width, height = style["width"], style["height"]
    image = Image.new("RGBA", (width, height - round(height * .91)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = width / 1920
    _, _, yellow = palette(style)
    draw.text((width / 2, 0), state["countdownLabel"], font=font(round(17 * scale), True), fill=yellow, anchor="mt")
    draw.text((width / 2, round(height * .025)), str(state["countdown"]), font=font(round(54 * scale), True), fill=yellow, anchor="mt")
    return image


def make_frame(project, at_ms, duration_ms):
    state = snapshot(project, at_ms, duration_ms)
    image = make_body(project, state).convert("RGBA")
    image.alpha_composite(make_clocks(project, state), (0, 0))
    image.alpha_composite(make_countdown(project, state), (0, round(project["style"]["height"] * .91)))
    return image.convert("RGB")


def cue_boundaries(project, duration):
    return sorted({0, duration} | {max(0, min(duration, cue[key] + project.get("cueOffsetMs", 0)))
                                  for cue in project["segments"] for key in ("startMs", "endMs")})


def write_concat(work, name, entries):
    lines = ["ffconcat version 1.0"]
    for filename, milliseconds in entries:
        lines.extend([f"file '{filename}'", "option framerate 1000", f"duration {milliseconds / 1000:.3f}"])
    lines.extend([f"file '{entries[-1][0]}'", "option framerate 1000"])
    (work / name).write_text("\n".join(lines) + "\n")


def prepare_layers(project, duration, work, report):
    boundaries = cue_boundaries(project, duration)
    entries = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        filename = f"body-{index:05}.png"
        make_body(project, snapshot(project, start, duration)).save(work / filename)
        entries.append((filename, end - start))
        report(2 + (index + 1) / (len(boundaries) - 1) * 8, "Preparing fixed prompt areas")
    write_concat(work, "body.ffconcat", entries)

    # Elapsed rounds down; remaining rounds up. Fractional track lengths have
    # their own countdown tick phase, which must also be represented.
    clock_times = sorted({0, duration} | set(range(1000, duration, 1000)) |
                         set(range(duration % 1000 or 1000, duration, 1000)))
    entries = []
    for index, (start, end) in enumerate(zip(clock_times, clock_times[1:])):
        filename = f"clock-{index:05}.png"
        make_clocks(project, snapshot(project, start, duration)).save(work / filename)
        entries.append((filename, end - start))
        if index % 25 == 0:
            report(10 + (index + 1) / (len(clock_times) - 1) * 5, "Preparing elapsed and remaining clocks")
    write_concat(work, "clocks.ffconcat", entries)

    footer_times = set(boundaries)
    for start, end in zip(boundaries, boundaries[1:]):
        target = snapshot(project, start, duration)["targetMs"]
        first = start + ((target - start) % 1000 or 1000)
        footer_times.update(range(first, end, 1000))
    footer_times = sorted(footer_times)
    entries, cache = [], {}
    for index, (start, end) in enumerate(zip(footer_times, footer_times[1:])):
        state = snapshot(project, start, duration)
        key = (state["countdownLabel"], state["countdown"])
        if key not in cache:
            filename = f"countdown-{len(cache):05}.png"
            make_countdown(project, state).save(work / filename)
            cache[key] = filename
        entries.append((cache[key], end - start))
        if index % 25 == 0:
            report(15 + (index + 1) / (len(footer_times) - 1) * 5, "Preparing cue countdowns")
    write_concat(work, "countdowns.ffconcat", entries)
    inputs = []
    for name in ("body", "clocks", "countdowns"):
        inputs += ["-f", "concat", "-safe", "0", "-i", name + ".ffconcat"]
    footer_y = round(project["style"]["height"] * .91)
    filters = f"[0:v]fps=25,format=rgba[body];[1:v]format=rgba[clocks];[2:v]format=rgba[countdown];[body][clocks]overlay=0:0:eof_action=repeat:format=rgb[timed];[timed][countdown]overlay=0:{footer_y}:eof_action=repeat:format=rgb,format=yuv420p[video]"
    return inputs, ["-filter_complex", filters, "-map", "[video]", "-map", "3:a:0"]
