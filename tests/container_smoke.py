"""Run against the ephemeral CI container, never against a user's NAS."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

for attempt in range(30):
    try:
        with urlopen(Request("http://127.0.0.1:8789/api/health", headers={"Host": "studio.example"}), timeout=2) as response:
            health = json.load(response)
        assert health["ready"] and health["mode"] == "server"
        break
    except (URLError, TimeoutError):
        time.sleep(1)
else:
    raise SystemExit("Container did not become ready")
try:
    urlopen(Request("http://127.0.0.1:8789/api/projects", headers={"Host": "studio.example"}), timeout=2)
    raise AssertionError("Unauthenticated project access was allowed")
except HTTPError as error:
    assert error.code == 401
    error.close()
print("Container boots, FFmpeg is ready, project access requires authentication.")
