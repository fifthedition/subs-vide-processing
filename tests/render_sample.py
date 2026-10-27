"""Create a short synthetic audio fixture and an actual rendered MP4 example."""
from pathlib import Path
import json
from test_studio import synthetic_audio, test_project
from studio import render_video, subtitle_text

folder = Path(__file__).resolve().parents[1] / "examples"
folder.mkdir(exist_ok=True)
project = test_project()
project["style"].update(layout="teleprompter", background="#000000", color="#ffffff")
synthetic_audio(folder / "synthetic-test-audio.wav")
(folder / "sample-session.json").write_text(json.dumps(project, ensure_ascii=False, indent=2))
(folder / "sample-subtitles.srt").write_text(subtitle_text(project), encoding="utf-8")
result = render_video(project, folder / "synthetic-test-audio.wav", folder / "render-validation.mp4")
print(json.dumps(result))
