"""Run against the ephemeral CI container, never against a user's NAS."""
import json
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

for attempt in range(30):
    try:
        with urlopen(Request("http://127.0.0.1:8789/api/health", headers={"Host": "studio.example"}), timeout=2) as response:
            health = json.load(response)
        assert health["ready"] and health["mode"] == "server"
        break
    except (URLError, OSError):
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

code = subprocess.check_output(["docker", "exec", "studio-ci", "cat", "/data/setup-code"], text=True).strip()
payload = json.dumps({"username": "ci-owner", "password": "ci-only-long-password", "code": code}).encode()
request = Request("http://127.0.0.1:8789/api/auth/setup", data=payload, headers={"Host": "studio.example", "Content-Type": "application/json"})
with urlopen(request, timeout=10) as response:
    cookie = response.headers["Set-Cookie"].split(";")[0]
    owner = json.load(response)
assert owner["role"] == "owner"
for route in ("projects", "catalog"):
    with urlopen(Request("http://127.0.0.1:8789/api/" + route, headers={"Host": "studio.example", "Cookie": cookie}), timeout=3) as response:
        assert json.load(response) == [], "Private content was bundled in the image"
print("First owner setup works; public image has no private projects or subtitle archive.")
