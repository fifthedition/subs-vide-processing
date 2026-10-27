import copy
import io
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from studio import ROOT, ConflictError, Store, ValidationError, import_subtitles, normalize_project, normalize_segments, render_video, subtitle_text, time_ms


def synthetic_audio(path, duration=8):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"".join(struct.pack("<h", int(math.sin(n * 2 * math.pi * 220 / 16000) * 2500)) for n in range(int(duration * 16000))))


def test_project():
    return normalize_project({"name": "Render verification", "cueOffsetMs": 1000, "segments": [
        {"id": "one", "startMs": 0, "endMs": 1000, "text": "Nadýchni sa. Ľahko a pokojne."},
        {"id": "two", "startMs": 2000, "endMs": 3000, "text": "Výdych. Uvoľni ramená."},
        {"id": "three", "startMs": 4000, "endMs": 5000, "text": "Dovoľ si chvíľu pokoja."}],
        "style": {"width": 1280, "height": 720, "fontSize": 64, "layout": "single"}})


class EditingTests(unittest.TestCase):
    def test_private_catalog_mount_seeds_without_duplication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subtitles.json"
            documents = [{"subtitle": {"id": 1, "name": "V01 Example - EN", "lang": "sk"}, "segments": [{"from_time": "00:00:01.000", "to_time": "00:00:02.000", "text": "Breathe."}]},
                         {"subtitle": {"id": 2, "name": "V01 Example - SK KATIKA", "lang": "sk"}, "segments": [{"from_time": "00:00:01.000", "to_time": "00:00:02.000", "text": "Nádych."}]}]
            path.write_text(json.dumps(documents))
            before = path.read_bytes()
            store = Store(directory, path)
            self.assertEqual(len(store.summaries()), 1)
            project = store.get(store.summaries()[0]["id"])
            self.assertEqual(project["sourceId"], 1)
            project["segments"][0]["text"] = "Opravený nádych."
            store.save(project["id"], project)
            restarted = Store(directory, path)
            self.assertEqual(len(restarted.summaries()), 1)
            self.assertEqual(restarted.get(project["id"])["segments"][0]["text"], "Opravený nádych.")
            self.assertEqual(path.read_bytes(), before)

    def test_archive_seed_and_source_preservation(self):
        archive = Path(os.environ.get("STUDIO_CATALOG", ROOT / "archive/subtitles.json"))
        if not archive.exists():
            self.skipTest("Private archive is intentionally excluded from this repository")
        before = archive.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            self.assertEqual(len(store.summaries()), 13)
            self.assertEqual(len(store.catalog), 35)
            self.assertEqual(sum(len(d["segments"]) for d in store.catalog), 7627)
            abundance = next(store.get(p["id"]) for p in store.summaries() if p["name"].startswith("V06"))
            self.assertEqual(abundance["archiveId"], 35)
            self.assertEqual(abundance["sourceId"], 33)
            abundance["segments"][0]["text"] = "Moja opravená slovenská veta."
            saved = store.save(abundance["id"], abundance)
            self.assertEqual(Store(directory).get(saved["id"])["segments"][0]["text"], "Moja opravená slovenská veta.")
            self.assertEqual(len(Store(directory).summaries()), 13)
        self.assertEqual(archive.read_bytes(), before)

    def test_stale_save_is_rejected_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            original = store.create("Editing example", test_project()["segments"])
            newer = copy.deepcopy(original)
            newer["name"] = "Saved correction"
            store.save(newer["id"], newer)
            with self.assertRaises(ConflictError):
                store.save(original["id"], original)
            self.assertEqual(store.get(original["id"])["name"], "Saved correction")

    def test_invalid_intervals_are_rejected(self):
        for segments in ([{"startMs": 100, "endMs": 100}], [{"startMs": -1, "endMs": 100}],
                         [{"startMs": 0, "endMs": 1000}, {"startMs": 999, "endMs": 2000}]):
            with self.subTest(segments=segments), self.assertRaises(ValidationError):
                normalize_segments(segments)

    def test_srt_and_webvtt_import_preserve_times_and_diacritics(self):
        source = "WEBVTT\n\nintro\n00:00.250 --> 00:02.500 align:center\nĽahký nádych.\n\nsecond\n00:03.000 --> 00:05.125\nUvoľni ramená &amp; čeľusť.\n"
        cues = import_subtitles(source)
        self.assertEqual([(s["startMs"], s["endMs"]) for s in cues], [(250, 2500), (3000, 5125)])
        self.assertEqual(cues[0]["text"], "Ľahký nádych.")
        self.assertEqual(cues[1]["text"], "Uvoľni ramená & čeľusť.")
        srt = subtitle_text({"segments": cues, "cueOffsetMs": 500})
        imported = import_subtitles(srt)
        self.assertEqual(imported[0]["startMs"], 750)
        self.assertEqual(imported[1]["text"], cues[1]["text"])

    def test_json_import_and_positive_offset(self):
        cues = import_subtitles(json.dumps({"segments": [{"id": 42, "from_time": "01:02:03.004", "to_time": "01:02:05.006", "text": "Pokoj."}]}))
        self.assertEqual(cues[0]["startMs"], 3723004)
        self.assertNotEqual(cues[0]["id"], "42")
        self.assertEqual(time_ms("02:03,4"), 123400)


class RenderingTests(unittest.TestCase):
    def test_music_only_video_timing_gaps_and_burned_text(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            music, output = directory / "music.wav", directory / "video.mp4"
            synthetic_audio(music)
            progress = []
            render_video(test_project(), music, output, lambda value, stage: progress.append(value))
            result = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)]))
            self.assertEqual(sorted(s["codec_type"] for s in result["streams"]), ["audio", "video"])
            self.assertLess(abs(float(result["format"]["duration"]) - 8), .08)
            self.assertEqual(next(s["codec_name"] for s in result["streams"] if s["codec_type"] == "video"), "h264")
            self.assertEqual(progress[-1], 100)
            for second, expect_text in ((.4, False), (1.4, True), (2.4, False), (3.4, True), (6.4, False)):
                raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", str(second), "-i", str(output), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"])
                image = Image.open(io.BytesIO(raw)).convert("L")
                bright = sum(count for luminance, count in enumerate(image.histogram()) if luminance > 100)
                self.assertEqual(bright > 100, expect_text, f"Wrong prompt state at {second} seconds")

    def test_export_rejects_prompts_after_music_and_negative_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "music.wav"
            synthetic_audio(path, 1)
            with self.assertRaisesRegex(ValidationError, "final prompt"):
                render_video(test_project(), path, Path(directory) / "video.mp4")
            project = test_project()
            project["cueOffsetMs"] = -100
            with self.assertRaisesRegex(ValidationError, "before the music"):
                render_video(project, path, Path(directory) / "video.mp4")


if __name__ == "__main__":
    unittest.main()
