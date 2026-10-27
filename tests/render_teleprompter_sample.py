"""Create a 23-second teleprompter demonstration with synthetic test audio."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import ROOT, normalize_project, render_video
from teleprompter import make_frame
from test_studio import synthetic_audio

folder = ROOT / "examples"
project = normalize_project({"name": "Motivácia · ukážka telepromptera", "cueOffsetMs": 0,
    "segments": [
        {"id": "intro", "startMs": 1000, "endMs": 6500, "text": "Nadýchni sa. Vnímaj pokoj a priestor okolo seba."},
        {"id": "release", "startMs": 8000, "endMs": 13500, "text": "S výdychom uvoľni ramená a dovoľ telu zmäknúť."},
        {"id": "continue", "startMs": 15000, "endMs": 20500, "text": "Pokračuj vlastným tempom. Dopraj si túto chvíľu pre seba."}],
    "style": {"width": 1280, "height": 720, "fontSize": 72, "background": "#000000", "color": "#ffffff", "layout": "teleprompter"}})
(folder / "teleprompter-session.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
synthetic_audio(folder / "teleprompter-test-audio.wav", 23)
render_video(project, folder / "teleprompter-test-audio.wav", folder / "teleprompter-demo.mp4")
make_frame(project, 9000, 23000).save(folder / "teleprompter-preview.png")
print("Created teleprompter-demo.mp4, project JSON, test audio, and preview image.")
