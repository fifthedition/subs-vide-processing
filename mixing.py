"""Final voice/music mix. The burned-subtitle video stream is copied intact."""
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from studio import ValidationError, probe_audio


def render_mix(guide, voice, destination, settings, progress=lambda value, stage: None):
    duration = probe_audio(guide)["durationMs"]
    info = probe_audio(voice)
    try:
        music_level = float(settings["musicVolume"])
        voice_level = float(settings["voiceVolume"])
        offset = float(settings["voiceOffsetMs"])
        if not all(math.isfinite(v) for v in (music_level, voice_level, offset)):
            raise ValueError()
        if not 0 <= music_level <= 1 or not 0 < voice_level <= 1 or abs(offset) > duration:
            raise ValueError()
    except (TypeError, KeyError, ValueError):
        raise ValidationError("Enter valid music, voice and alignment settings.") from None
    if offset >= duration or offset + info["durationMs"] <= 0:
        raise ValidationError("The narration does not overlap the guide video. Adjust its offset.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mix-", dir=destination.parent) as temporary:
        work = Path(temporary)
        partial = work / "output.mp4"
        timing = ("atrim=start=" + f"{-offset/1000:.6f}," if offset < 0 else "") + "asetpts=PTS-STARTPTS"
        if offset > 0:
            timing += f",adelay={round(offset)}:all=1"
        stereo = "pan=stereo|c0=c0|c1=c0," if info["channels"] == 1 else ""
        filters = (f"[0:a:0]asetpts=PTS-STARTPTS,aresample=48000,volume={music_level:.8f},"
                   f"apad,atrim=duration={duration/1000:.6f}[music];"
                   f"[1:a:0]{stereo}{timing},aresample=48000,aformat=channel_layouts=stereo,"
                   f"volume={voice_level:.8f},apad,atrim=duration={duration/1000:.6f}[voice];"
                   "[music][voice]amix=inputs=2:duration=first:normalize=0,"
                   "alimiter=limit=0.95:level=0:latency=1[audio]")
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(Path(guide).resolve()),
                   "-i", str(Path(voice).resolve()), "-filter_complex", filters, "-map", "0:v:0", "-map", "[audio]",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
                   "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(partial)]
        # Bound both audio branches in the graph. A global -t with copied video
        # can stop filtered audio at video EOF on older FFmpeg versions, even
        # when the guide's music continues beyond its last video packet.
        progress(2, "Mixing enhanced narration with stereo music")
        with (work / "error.log").open("w+") as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True)
            try:
                for line in process.stdout:
                    if line.startswith("out_time_us="):
                        try:
                            progress(min(99, 2 + 97 * int(line.split("=", 1)[1]) / (duration * 1000)), "Mixing enhanced narration with stereo music")
                        except ValueError:
                            pass
                code = process.wait()
            except BaseException:
                process.terminate(); process.wait()
                raise
            finally:
                process.stdout.close()
            if code:
                errors.seek(0)
                raise ValidationError("Final audio mix failed: " + errors.read()[-1200:])
        shutil.move(str(partial), destination)
    progress(100, "Complete")
    return {"durationMs": duration, "bytes": destination.stat().st_size}

