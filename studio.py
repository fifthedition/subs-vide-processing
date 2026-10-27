"""Persistent session editing and a music-only, burned-text video renderer."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import copy
import html
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
FONT = ROOT / "static/assets/Inter.ttf"
DEFAULT_STYLE = {"fontSize": 64, "background": "#000000", "color": "#ffffff", "width": 1920, "height": 1080, "layout": "teleprompter"}


class ValidationError(ValueError):
    pass


class ConflictError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def time_ms(value):
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValidationError("A cue time is not a finite number.")
        return round(value)
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?", str(value).strip())
    if not match:
        raise ValidationError(f"Invalid time: {str(value)[:30]}. Use HH:MM:SS.mmm.")
    h, m, s, fraction = match.groups()
    if int(m) >= 60 or int(s) >= 60:
        raise ValidationError("Minutes and seconds must be below 60.")
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int((fraction or "").ljust(3, "0") or 0)


def stamp(ms, separator="."):
    h, rest = divmod(int(ms), 3600000)
    m, rest = divmod(rest, 60000)
    s, fraction = divmod(rest, 1000)
    return f"{h:02}:{m:02}:{s:02}{separator}{fraction:03}"


def display_language(metadata):
    return "en" if re.search(r"\bEN\b", metadata["name"]) else metadata.get("lang", "sk")


def normalize_segments(segments):
    result = []
    if not isinstance(segments, list) or len(segments) > 10000:
        raise ValidationError("A session must contain a list of at most 10,000 cues.")
    for item in segments:
        if not isinstance(item, dict):
            raise ValidationError("A cue must be an object.")
        start = time_ms(item.get("startMs", item.get("from_time", 0)))
        end = time_ms(item.get("endMs", item.get("to_time", 0)))
        text = str(item.get("text", ""))
        if len(text) > 20000:
            raise ValidationError("A cue is too long; split it into smaller prompts.")
        result.append({"id": str(item.get("id") or uid()), "startMs": start, "endMs": end, "text": text})
    result.sort(key=lambda s: s["startMs"])
    seen = set()
    previous = None
    for index, segment in enumerate(result, 1):
        if segment["id"] in seen:
            raise ValidationError("Cue IDs must be unique.")
        seen.add(segment["id"])
        if segment["startMs"] < 0 or segment["endMs"] <= segment["startMs"]:
            raise ValidationError(f"Cue {index} needs a positive duration and a nonnegative start.")
        if previous is not None and segment["startMs"] < previous["endMs"]:
            raise ValidationError(f"Cues {index - 1} and {index} overlap. Adjust their times.")
        previous = segment
    return result


def normalize_project(project):
    result = copy.deepcopy(project)
    result["name"] = str(project.get("name", "Untitled session")).strip()[:160] or "Untitled session"
    result["segments"] = normalize_segments(project.get("segments", []))
    result["cueOffsetMs"] = time_ms(project.get("cueOffsetMs", 0))
    style = {**DEFAULT_STYLE, **project.get("style", {})}
    try:
        style["fontSize"] = max(28, min(100, int(style["fontSize"])))
        width, height = int(style["width"]), int(style["height"])
    except (ValueError, TypeError):
        raise ValidationError("Invalid video style.")
    if (width, height) not in ((1920, 1080), (1280, 720)):
        raise ValidationError("Choose Full HD · 1080p output.")
    # Older saved sessions may say 720p. All new previews and exports are Full HD.
    style["width"], style["height"] = 1920, 1080
    if style["layout"] not in ("teleprompter", "single"):
        raise ValidationError("Choose the teleprompter or single-prompt video layout.")
    for key in ("background", "color"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(style[key])):
            raise ValidationError("Use six-digit hex colors.")
    result["style"] = style
    return result


def import_subtitles(text):
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if text.lstrip().startswith(("{", "[")):
        data = json.loads(text)
        segments = data.get("segments") if isinstance(data, dict) else data
        if segments is None:
            raise ValidationError("JSON needs a segments list, or a single exported project.")
        # Imported IDs belong to another document; assign fresh identities.
        return normalize_segments([{**s, "id": uid()} for s in segments])
    pattern = re.compile(r"^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})[^\n]*\n", re.M)
    matches = list(pattern.finditer(text))
    if not matches:
        raise ValidationError("No subtitle cues found. Import SRT, VTT, or a project JSON file.")
    cues = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip("\n")
        # A numeric or named cue identifier precedes the next timestamp.
        if index + 1 < len(matches):
            body = re.sub(r"\n\s*\n[^\n]+\s*$", "", body)
        body = re.sub(r"</?(?:b|i|u|c|v|lang|ruby|rt)(?:[ .][^>]*)?>", "", body)
        cues.append({"id": uid(), "startMs": time_ms(match[1]), "endMs": time_ms(match[2]), "text": html.unescape(body)})
    return normalize_segments(cues)


def subtitle_text(project, fmt="srt"):
    offset = project.get("cueOffsetMs", 0)
    blocks = []
    for index, cue in enumerate(project["segments"], 1):
        start, end = cue["startMs"] + offset, cue["endMs"] + offset
        if start < 0:
            raise ValidationError("The prompt offset moves a cue before the start of the session.")
        text = "\n".join(line if line.strip() else line + "\u00a0" for line in cue["text"].split("\n"))
        if fmt == "vtt":
            text = html.escape(text, quote=False)
        separator = "," if fmt == "srt" else "."
        blocks.append(f"{index}\n{stamp(start, separator)} --> {stamp(end, separator)}\n{text}\n")
    return ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n".join(blocks)


class Store:
    def __init__(self, directory, catalog_path=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "media").mkdir(exist_ok=True)
        (self.directory / "exports").mkdir(exist_ok=True)
        self.database = self.directory / "studio.sqlite3"
        # Archives belong in a private data volume, never in a public image.
        catalog_path = Path(catalog_path or os.environ.get("STUDIO_CATALOG", self.directory / "subtitles.json"))
        self.catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else []
        self.catalog_by_id = {str(d["subtitle"]["id"]): d for d in self.catalog}
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT,revision INTEGER,payload TEXT,updated TEXT);
                CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,payload TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            """)
            for row in db.execute("SELECT id,payload FROM jobs").fetchall():
                job = json.loads(row["payload"])
                if not job.get("protocol") and job["status"] in ("queued", "rendering"):
                    job.update(status="failed", error="The app stopped during this export. Start a new export to retry.")
                    db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(job), row["id"]))
            seeded = db.execute("SELECT value FROM settings WHERE key='seeded'").fetchone()
        if not seeded and self.catalog:
            journeys = {}
            for document in self.catalog:
                meta = document["subtitle"]
                if display_language(meta) != "sk":
                    continue
                code = meta["name"].split()[0]
                score = ("KATIKA" in meta["name"].upper()) * 3 + ("KTK" in meta["name"].upper()) * 2
                if code not in journeys or score > journeys[code][0]:
                    journeys[code] = (score, meta["id"])
            for code in sorted(journeys):
                self.create_from_archive(journeys[code][1])
            with self.connection() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES('seeded','1')")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, project_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise KeyError("Session not found.")
        return normalize_project(json.loads(row["payload"]))

    def summaries(self):
        with self.connection() as db:
            projects = [json.loads(r[0]) for r in db.execute("SELECT payload FROM projects ORDER BY name")]
        return [{"id": p["id"], "name": p["name"], "revision": p["revision"], "count": len(p["segments"]),
                 "endMs": max((s["endMs"] for s in p["segments"]), default=0), "musicId": p.get("musicId"), "updatedAt": p["updatedAt"]} for p in projects]

    def create(self, name, segments, source_id=None, archive_id=None, reference=None):
        project = normalize_project({"id": uid(), "name": name, "language": "sk", "segments": segments,
            "sourceId": source_id, "archiveId": archive_id, "cueOffsetMs": 0, "musicId": None, "style": DEFAULT_STYLE,
            "revision": 1, "updatedAt": now()})
        if reference is not None:
            project["reference"] = {"name": str(reference.get("name", "Original transcript"))[:200],
                "language": str(reference.get("language", "auto"))[:20],
                "segments": normalize_segments(reference.get("segments", [])), "mediaId": reference.get("mediaId")}
            if project["reference"]["mediaId"]:
                self.media(project["reference"]["mediaId"])
        with self.connection() as db:
            db.execute("INSERT INTO projects VALUES(?,?,?,?,?)", (project["id"], project["name"], 1, json.dumps(project, ensure_ascii=False), project["updatedAt"]))
        return project

    def create_from_archive(self, subtitle_id):
        document = self.catalog_by_id[str(subtitle_id)]
        meta = document["subtitle"]
        code = meta["name"].split()[0]
        source = next((d["subtitle"]["id"] for d in self.catalog if d["subtitle"]["name"].split()[0] == code and display_language(d["subtitle"]) == "en"), None)
        name = re.sub(r"\s*-\s*(?:Script\s+)?(?:SK|EN)\b.*$", "", meta["name"], flags=re.I)
        return self.create(name, [{**s, "id": uid()} for s in document["segments"]], source, meta["id"])

    def save(self, project_id, payload):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload,revision FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise KeyError("Session not found.")
            if payload.get("revision") != row["revision"]:
                raise ConflictError("This session changed in another window. Download your draft JSON before reloading.")
            previous = json.loads(row["payload"])
            project = normalize_project({**previous, **{k: payload[k] for k in ("name", "segments", "sourceId", "cueOffsetMs", "style", "musicId") if k in payload}})
            if project.get("musicId"):
                if self.media(project["musicId"]).get("purpose") == "reference":
                    raise ValidationError("Choose your separate music-only track. Source recordings are for transcription and review.")
            if project.get("sourceId") is not None and str(project["sourceId"]) not in self.catalog_by_id:
                raise ValidationError("Unknown reference subtitle.")
            project.update(id=project_id, revision=row["revision"] + 1, updatedAt=now())
            db.execute("UPDATE projects SET name=?,revision=?,payload=?,updated=? WHERE id=?",
                (project["name"], project["revision"], json.dumps(project, ensure_ascii=False), project["updatedAt"], project_id))
        return project

    def media(self, media_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM media WHERE id=?", (media_id,)).fetchone()
        if not row:
            raise KeyError("Music not found.")
        return json.loads(row[0])

    def put_media(self, media):
        with self.connection() as db:
            db.execute("INSERT INTO media VALUES(?,?)", (media["id"], json.dumps(media)))

    def put_job(self, job):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?)", (job["id"], json.dumps(job)))

    def jobs(self, project_id=None):
        with self.connection() as db:
            jobs = [json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs")]
        return sorted((j for j in jobs if project_id is None or j["projectId"] == project_id), key=lambda j: j["createdAt"], reverse=True)


def probe_audio(path):
    if not shutil.which("ffprobe"):
        raise ValidationError("FFmpeg/ffprobe is missing. See the launch instructions.")
    process = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=60)
    if process.returncode:
        raise ValidationError("That file could not be read as audio.")
    data = json.loads(process.stdout)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration", audio.get("duration", 0) if audio else 0))
    if not audio or not math.isfinite(duration) or duration <= 0 or duration > 12 * 3600:
        raise ValidationError("Choose an audio file between 0 and 12 hours long.")
    return {"durationMs": round(duration * 1000), "channels": audio.get("channels", 0),
            "codec": audio.get("codec_name", ""), "sampleRate": int(audio.get("sample_rate") or 0),
            "bitRate": int(audio.get("bit_rate") or 0), "channelLayout": audio.get("channel_layout", "")}


def export_audio_options(info):
    """Keep stereo AAC packets intact; otherwise preserve rate and encode stereo.

    Never sum a stereo recording to mono: independent left/right channels matter
    for binaural tracks. A mono source becomes dual mono, not invented stereo.
    AAC cannot retain PCM bit depth; its high-quality fallback is 320 kbit/s.
    """
    if info["codec"] == "aac" and info["channels"] == 2:
        return ["-c:a", "copy"]
    options = ["-c:a", "aac", "-b:a", "320k", "-ac", "2"]
    if info["channels"] == 1:
        # Duplicate at unity gain instead of the default -3 dB mono upmix.
        options += ["-af", "pan=stereo|c0=c0|c1=c0"]
    rates = (7350, 8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000)
    source_rate = info.get("sampleRate") or 48000
    rate = min(rates, key=lambda candidate: abs(candidate - source_rate))
    return options + ["-ar", str(rate)]


def wrap_text(draw, text, font, maximum):
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=font) <= maximum:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            for letter in word:
                if line and draw.textlength(line + letter, font=font) > maximum:
                    lines.append(line)
                    line = ""
                line += letter
        if line:
            lines.append(line)
    return lines or [""]


def make_frame(project, text, destination=None):
    style = {**DEFAULT_STYLE, **project.get("style", {})}
    width, height = style["width"], style["height"]
    image = Image.new("RGB", (width, height), style["background"])
    draw = ImageDraw.Draw(image)
    size = round(style["fontSize"] * width / 1920)
    while True:
        font = ImageFont.truetype(str(FONT), size=size)
        lines = wrap_text(draw, text, font, width * .82)
        line_height = round(size * 1.42)
        if len(lines) * line_height <= height * .76 or size <= 14:
            break
        size -= 1
    if len(lines) * line_height > height * .82:
        raise ValidationError("A prompt is too long to fit on screen. Split that cue before exporting.")
    top = (height - len(lines) * line_height) / 2
    for index, line in enumerate(lines):
        draw.text((width / 2, top + index * line_height), line, font=font, fill=style["color"], anchor="mt")
    if destination:
        image.save(destination, "PNG")
    return image


def render_video(project, music_path, destination, progress=lambda value, stage: None):
    """Snapshot in, MP4 out. The only audio source is the supplied music file."""
    project = normalize_project(project)
    info = probe_audio(music_path)
    duration = info["durationMs"]
    offset = project.get("cueOffsetMs", 0)
    if not project["segments"]:
        raise ValidationError("Add at least one Slovak prompt before exporting.")
    if any(s["startMs"] + offset < 0 for s in project["segments"]):
        raise ValidationError("The prompt offset moves a cue before the music starts.")
    if max(s["endMs"] + offset for s in project["segments"]) > duration + 50:
        raise ValidationError("The final prompt ends after the music. Adjust its timing or choose a longer track.")
    if not shutil.which("ffmpeg"):
        raise ValidationError("FFmpeg is missing. See the launch instructions.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=destination.parent) as temporary:
        work = Path(temporary)
        from teleprompter import prepare_layers, write_concat
        if project["style"]["layout"] == "teleprompter":
            inputs, mapping = prepare_layers(project, duration, work, progress)
        else:
            entries = []
            cursor = 0
            empty = work / "blank.png"
            make_frame(project, "", empty)
            for index, cue in enumerate(project["segments"]):
                start, end = cue["startMs"] + offset, min(cue["endMs"] + offset, duration)
                if start > cursor:
                    entries.append((empty.name, start - cursor))
                frame = work / f"cue-{index:05}.png"
                make_frame(project, cue["text"], frame)
                entries.append((frame.name, end - start))
                cursor = end
                progress(5 + (index + 1) / len(project["segments"]) * 15, "Preparing prompts")
            if cursor < duration:
                entries.append((empty.name, duration - cursor))
            write_concat(work, "frames.ffconcat", entries)
            inputs = ["-f", "concat", "-safe", "0", "-i", "frames.ffconcat"]
            mapping = ["-map", "0:v:0", "-map", "1:a:0"]
        partial_output = work / "output.mp4"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
                   "-i", str(Path(music_path).resolve()), *mapping, "-c:v", "libx264", "-preset", "veryfast",
                   "-tune", "stillimage", "-crf", "16", "-r", "25", "-pix_fmt", "yuv420p", *export_audio_options(info),
                   "-t", f"{duration / 1000:.3f}", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(partial_output)]
        progress(20, "Rendering video")
        with (work / "ffmpeg-error.log").open("w+") as errors:
            process = subprocess.Popen(command, cwd=work, stdout=subprocess.PIPE, stderr=errors, text=True)
            try:
                for line in process.stdout:
                    if line.startswith("out_time_us="):
                        try:
                            completed = int(line.split("=", 1)[1]) / 1000
                            progress(min(99, 20 + 79 * completed / duration), "Rendering video")
                        except ValueError:
                            pass
                code = process.wait()
            except BaseException:
                process.terminate()
                process.wait()
                raise
            finally:
                process.stdout.close()
            if code:
                errors.seek(0)
                raise ValidationError("Video export failed: " + errors.read()[-1600:])
        shutil.move(str(partial_output), destination)
    progress(100, "Complete")
    return {"durationMs": duration, "bytes": destination.stat().st_size}
