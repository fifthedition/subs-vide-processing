#!/usr/bin/env python3
"""Manually drain the NAS export queue, then exit. No login item or daemon."""
from contextlib import contextmanager
import argparse
import fcntl
import getpass
import json
import os
from pathlib import Path
import shutil
import signal
import secrets
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from export_queue import PROTOCOL, RENDERER_VERSION, CHUNK_BYTES, file_hash
from studio import ValidationError, render_video

CONFIG_ROOT = Path.home() / "Library/Application Support/BreathworkStudio"
CACHE_ROOT = Path.home() / "Library/Caches/BreathworkStudio"
KEYCHAIN_SERVICE = "eu.nasforlife.breathworkers.renderer"


class WorkerError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, url, token, allow_local=False):
        parts = urlsplit(url)
        if parts.scheme != "https" and not (allow_local and parts.scheme == "http" and parts.hostname == "127.0.0.1"):
            raise WorkerError("Use your HTTPS app address.")
        if not parts.hostname or parts.path not in ("", "/") or parts.username or parts.password or parts.query or parts.fragment:
            raise WorkerError("Use just the app address, for example https://breathworkers.nasforlife.eu")
        self.url = url.rstrip("/")
        self.token = token

    def request(self, route, payload=None, *, data=None, headers=None):
        body = json.dumps(payload).encode() if payload is not None else data
        request = Request(self.url + route, data=body, headers={"Authorization": "Bearer " + self.token,
                          "Content-Type": "application/json" if payload is not None else "application/octet-stream", **(headers or {})},
                          method="POST" if body is not None else "GET")
        for attempt in range(3):
            try:
                with build_opener(NoRedirect).open(request, timeout=60) as response:
                    return json.loads(response.read(25 * 1024 * 1024))
            except HTTPError as error:
                try:
                    detail = json.loads(error.read(4096)).get("error", "")
                except (ValueError, AttributeError):
                    detail = ""
                status = error.code
                error.close()
                if status not in (429, 502, 503, 504) or attempt == 2:
                    raise WorkerError(detail or f"The NAS returned HTTP {status}.") from None
            except (URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise WorkerError("Cannot reach the NAS. Check the connection and run the renderer again.") from None
            time.sleep(attempt + 1)

    def download(self, job, destination, progress):
        music = job["music"]
        if destination.exists() and destination.stat().st_size == music["bytes"] and file_hash(destination) == music["sha256"]:
            return
        partial = destination.with_suffix(destination.suffix + ".part")
        for attempt in range(3):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset >= music["bytes"]:
                partial.unlink()
                offset = 0
            request = Request(self.url + "/api/worker/jobs/" + job["id"] + "/music", headers={
                "Authorization": "Bearer " + self.token, "X-Render-Attempt": job["attempt"], "Range": f"bytes={offset}-"})
            try:
                with build_opener(NoRedirect).open(request, timeout=60) as response:
                    if response.status == 206:
                        if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                            raise WorkerError("The NAS returned an invalid resume position.")
                    elif response.status == 200:
                        offset = 0
                    else:
                        raise WorkerError("The music download could not be resumed.")
                    with partial.open("ab" if offset else "wb") as output:
                        while chunk := response.read(CHUNK_BYTES):
                            output.write(chunk)
                            progress(0, f"Downloading music · {output.tell() / music['bytes']:.0%}")
                if partial.stat().st_size != music["bytes"]:
                    raise OSError("Incomplete download")
                if file_hash(partial) != music["sha256"]:
                    partial.unlink()
                    raise WorkerError("Music failed its integrity check. Run the renderer again to download a fresh copy.")
                partial.replace(destination)
                return
            except HTTPError as error:
                error.close()
                raise WorkerError("The music is unavailable or this render attempt expired.") from None
            except (URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise WorkerError("Music download interrupted. The saved portion can be resumed next time.") from None
                time.sleep(attempt + 1)


class Heartbeat:
    def __init__(self, client, job):
        self.client, self.job = client, job
        self.progress, self.stage = 0, "Preparing export"
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self.run, name="render-heartbeat")

    def run(self):
        last_ok = time.monotonic()
        while not self.stop.wait(10):
            try:
                self.client.request("/api/worker/jobs/" + self.job["id"] + "/heartbeat",
                    {"attempt": self.job["attempt"], "progress": self.progress, "stage": self.stage})
                last_ok = time.monotonic()
            except WorkerError:
                if time.monotonic() - last_ok > 100:
                    self.lost.set()
                    return

    def report(self, progress, stage):
        if self.lost.is_set():
            raise WorkerError("Lost contact with the NAS. Start the worker again when the connection returns.")
        self.progress, self.stage = round(progress, 1), stage
        print(f"\r{self.progress:5.1f}% · {stage:65.65}", end="", flush=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
        print(flush=True)


@contextmanager
def keep_awake():
    # Only active while a claimed job is downloading, rendering or uploading.
    process = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if sys.platform == "darwin" else None
    try:
        yield
    finally:
        if process:
            process.terminate()
            process.wait()


def trim_cache(directory, limit=5 * 1024 ** 3):
    paths = sorted((p for p in directory.glob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    used = 0
    for path in paths:
        used += path.stat().st_size
        if used > limit:
            path.unlink(missing_ok=True)


def process_job(client, job, cache):
    media_dir, output_dir = cache / "media", cache / "exports"
    media_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    music = media_dir / (job["music"]["sha256"] + Path(job["music"]["storedName"]).suffix)
    output = output_dir / (job["id"] + ".mp4")
    # An immutable job can reuse a fully rendered local MP4 after an upload failure.
    manifest_path = output.with_suffix(".json")
    fingerprint = file_hash_bytes(json.dumps({"project": job["project"], "music": job["music"]["sha256"], "renderer": RENDERER_VERSION}, sort_keys=True).encode())
    with keep_awake(), Heartbeat(client, job) as heartbeat:
        client.download(job, music, heartbeat.report)
        music.touch()
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if not output.exists() or manifest.get("fingerprint") != fingerprint or manifest.get("sha256") != file_hash(output):
            render_video(job["project"], music, output, lambda value, stage: heartbeat.report(value * .9, stage))
            manifest = {"fingerprint": fingerprint, "sha256": file_hash(output), "bytes": output.stat().st_size}
            manifest_path.write_text(json.dumps(manifest))
        begin = {"attempt": job["attempt"], "bytes": manifest["bytes"], "sha256": manifest["sha256"]}
        state = client.request("/api/worker/jobs/" + job["id"] + "/upload", begin)
        offset = state["offset"]
        with output.open("rb") as handle:
            handle.seek(offset)
            while chunk := handle.read(CHUNK_BYTES):
                state = client.request("/api/worker/jobs/" + job["id"] + "/chunk", data=chunk,
                    headers={"X-Render-Attempt": job["attempt"], "X-Upload-Offset": str(offset)})
                offset = state["offset"]
                heartbeat.report(90 + 9 * offset / manifest["bytes"], "Uploading video")
        client.request("/api/worker/jobs/" + job["id"] + "/complete", {"attempt": job["attempt"]})
        heartbeat.report(100, "Ready to download from the NAS")
    output.unlink(missing_ok=True)
    manifest_path.unlink(missing_ok=True)
    trim_cache(media_dir)


def file_hash_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def drain(client, cache):
    completed, failed = 0, 0
    while True:
        job = client.request("/api/worker/claim", {"protocol": PROTOCOL, "rendererVersion": RENDERER_VERSION, "requestId": secrets.token_hex(16)})["job"]
        if job is None:
            print(f"Queue empty. {completed} video(s) uploaded; {failed} failed. Renderer stopped.", flush=True)
            return 1 if failed else 0
        print(f"Rendering: {job['project']['name']} (revision {job['project']['revision']})", flush=True)
        try:
            process_job(client, job, cache)
            completed += 1
        except KeyboardInterrupt:
            try:
                client.request("/api/worker/jobs/" + job["id"] + "/release", {"attempt": job["attempt"]})
            except WorkerError:
                pass
            print("Stopped. Unfinished work will remain queued on the NAS.", flush=True)
            return 130
        except Exception as error:
            # These errors originate from our renderer/client, never include a credential.
            message = str(error)[:1200]
            print("Export failed: " + message, flush=True)
            try:
                client.request("/api/worker/jobs/" + job["id"] + "/fail", {"attempt": job["attempt"], "error": message})
            except WorkerError:
                raise WorkerError("The NAS is unreachable. The unfinished job will return to the queue automatically.") from None
            failed += 1


def keychain_get():
    result = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", "renderer", "-w"], capture_output=True, text=True)
    if result.returncode:
        raise WorkerError("No renderer token in Keychain. Run Configure-Mac-Renderer.command first.")
    return result.stdout.strip()


def configure():
    if sys.platform != "darwin":
        raise WorkerError("Interactive pairing uses macOS Keychain. For testing use --url and --token-file.")
    url = input("App address [https://breathworkers.nasforlife.eu]: ").strip() or "https://breathworkers.nasforlife.eu"
    token = getpass.getpass("Renderer token from the owner settings (hidden): ").strip()
    client = Client(url, token)
    info = client.request("/api/worker/info")
    if info["rendererVersion"] != RENDERER_VERSION:
        raise WorkerError("Update this Mac renderer to the NAS app's version before pairing.")
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
        raise WorkerError("Invalid renderer token.")
    # Interactive security commands take the password over stdin, not process argv.
    command = f'add-generic-password -U -s {KEYCHAIN_SERVICE} -a renderer -w {token}\n'
    result = subprocess.run(["/usr/bin/security", "-i"], input=command, text=True, capture_output=True)
    if result.returncode or keychain_get() != token:
        raise WorkerError("Could not save the renderer token in Keychain.")
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    (CONFIG_ROOT / "renderer.json").write_text(json.dumps({"url": client.url}))
    print("Paired. Run Render-Queued-Videos.command whenever you want to export queued videos.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--token-file", type=Path, help="Private credential file, for non-macOS testing")
    parser.add_argument("--cache", type=Path, default=CACHE_ROOT)
    parser.add_argument("--allow-local-test", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args()
    os.umask(0o077)
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    try:
        if options.configure:
            configure()
            return 0
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise WorkerError("Install FFmpeg first: brew install ffmpeg")
        options.cache.mkdir(parents=True, exist_ok=True)
        with (options.cache / "worker.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkerError("The renderer is already running in another Terminal window.") from None
            if options.url:
                url = options.url
            else:
                config = CONFIG_ROOT / "renderer.json"
                if not config.is_file():
                    raise WorkerError("Run Configure-Mac-Renderer.command to pair this Mac first.")
                url = json.loads(config.read_text())["url"]
            token = options.token_file.read_text().strip() if options.token_file else keychain_get()
            return drain(Client(url, token, options.allow_local_test), options.cache)
    except KeyboardInterrupt:
        print("Renderer stopped.")
        return 130
    except (WorkerError, ValidationError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
