import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image, ImageChops, ImageStat
from studio import ROOT, ValidationError, normalize_project, render_video
from teleprompter import make_frame, snapshot
from test_studio import synthetic_audio, test_project


def presenter_project():
    project = test_project()
    project["name"] = "Motivácia · slovenské vedenie"
    project["cueOffsetMs"] = 1250
    project["style"].update(layout="teleprompter", background="#000000", color="#ffffff")
    return project


class TeleprompterTests(unittest.TestCase):
    def test_previous_current_next_and_countdown_across_gaps_and_end(self):
        project = presenter_project()
        cases = [(0, (-1, -1, 0), 2, "ĎALŠÍ TEXT O"),
                 (1250, (-1, 0, 1), 1, "DO KONCA TEXTU"),
                 (2250, (0, -1, 1), 1, "ĎALŠÍ TEXT O"),
                 (3250, (0, 1, 2), 1, "DO KONCA TEXTU"),
                 (4250, (1, -1, 2), 1, "ĎALŠÍ TEXT O"),
                 (5250, (1, 2, -1), 1, "DO KONCA TEXTU"),
                 (6250, (2, -1, -1), 3, "DO KONCA HUDBY"),
                 (8375, (2, -1, -1), 0, "DO KONCA HUDBY")]
        for at, indices, seconds, label in cases:
            with self.subTest(time=at):
                state = snapshot(project, at, 8375)
                self.assertEqual(tuple(state[key] for key in ("previous", "current", "next")), indices)
                self.assertEqual((state["countdown"], state["countdownLabel"]), (seconds, label))
        self.assertEqual(snapshot(project, 0, 8375)["remaining"], "00:09")
        self.assertEqual(snapshot(project, 375, 8375)["remaining"], "00:08")
        self.assertEqual(snapshot(project, 1000, 8375)["elapsed"], "00:01")
        self.assertEqual(snapshot(project, 999999, 8375)["remaining"], "00:00")
        self.assertEqual(snapshot(project, 3661000, 3662500)["elapsed"], "01:01:01")

    def test_browser_state_and_canvas_draw_match_render_state(self):
        project = presenter_project()
        times = [0, 374, 375, 1000, 1249, 1250, 2250, 3250, 4250, 5250, 6250, 8375, 9999]
        result = subprocess.run(["node", str(ROOT / "tests/test_teleprompter.js")],
            input=json.dumps({"project": project, "times": times, "duration": 8375}), capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [snapshot(project, at, 8375) for at in times])

    def test_rendered_layers_update_clocks_without_moving_prompt_areas(self):
        project = presenter_project()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            music, video = directory / "music.wav", directory / "video.mp4"
            synthetic_audio(music, 8.375)
            render_video(project, music, video)
            info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)]))
            self.assertEqual(sorted(stream["codec_type"] for stream in info["streams"]), ["audio", "video"])
            self.assertLess(abs(float(info["format"]["duration"]) - 8.375), .08)
            for second in (.2, .5, 1.1, 1.4, 2.4, 3.4, 3.9, 4.4, 6.4, 8.1):
                data = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", str(second), "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"])
                decoded = Image.open(io.BytesIO(data)).convert("RGB")
                expected = make_frame(project, round(second * 1000), 8375)
                for name, bounds in (("clocks", (0, 0, 1280, 115)), ("previous", (70, 155, 1210, 250)),
                                     ("current", (70, 270, 1210, 485)), ("next", (70, 515, 1210, 640)),
                                     ("countdown", (470, 655, 810, 720))):
                    difference = ImageChops.difference(decoded.crop(bounds), expected.crop(bounds))
                    self.assertLess(max(ImageStat.Stat(difference).mean), 2.5, f"{name} does not match at {second}s")
            # The same supplied music remains the sole audible input.
            original = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(music), "-t", "8", "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"])
            encoded = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(video), "-t", "8", "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"])
            import array
            a, b = array.array("f"), array.array("f")
            a.frombytes(original); b.frombytes(encoded)
            correlation = sum(x*y for x,y in zip(a,b)) / (sum(x*x for x in a) * sum(y*y for y in b)) ** .5
            self.assertGreater(correlation, .98)

    def test_defaults_and_explicit_single_layout_survive_import(self):
        self.assertEqual(normalize_project({"segments": []})["style"]["layout"], "teleprompter")
        self.assertEqual(normalize_project(test_project())["style"]["layout"], "single")
        with self.assertRaisesRegex(ValidationError, "layout"):
            normalize_project({"segments": [], "style": {"layout": "scrolling"}})


if __name__ == "__main__":
    unittest.main()
