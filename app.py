#!/usr/bin/env python3
"""Breathwork Studio: local editor or authenticated NAS service."""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote, quote
import argparse
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import hmac

from studio import ROOT, Store, ValidationError, ConflictError, display_language, import_subtitles, make_frame, normalize_project, now, probe_audio, render_video, subtitle_text, uid
from services import DraftService
from security import Security, AccessError
from export_queue import ExportQueue, public_job, PROTOCOL, RENDERER_VERSION, CHUNK_BYTES
from uploads import Uploads


class Application:
    def __init__(self, directory, remote=False, public_url=None):
        self.store = Store(directory)
        self.remote = remote
        self.public_url = (public_url or "").rstrip("/")
        if remote and (urlsplit(self.public_url).scheme != "https" or not urlsplit(self.public_url).hostname or urlsplit(self.public_url).path):
            raise ValidationError("Server mode requires STUDIO_PUBLIC_URL, for example https://breathworkers.nasforlife.eu")
        self.security = Security(self.store) if remote else None
        self.queue = ExportQueue(self.store)
        self.uploads = Uploads(self.store)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-export")
        self.drafts = DraftService(self.store)

    def render(self, project, expected_revision):
        if self.remote:
            return self.queue.enqueue(project, expected_revision)
        if project["revision"] != expected_revision:
            raise ConflictError("Save your current changes before exporting.")
        if not project.get("musicId"):
            raise ValidationError("Add your music-only track before exporting a video.")
        music = self.store.media(project["musicId"])
        if music.get("purpose") == "reference":
            raise ValidationError("Source recordings cannot be used as an export's music track.")
        normalized = normalize_project(project)
        offset = normalized["cueOffsetMs"]
        if not normalized["segments"]:
            raise ValidationError("Add at least one prompt.")
        if normalized["segments"][0]["startMs"] + offset < 0:
            raise ValidationError("The prompt offset moves the first cue before the music starts.")
        if normalized["segments"][-1]["endMs"] + offset > music["durationMs"] + 50:
            raise ValidationError("The final prompt ends after your music. Adjust its time or use a longer track.")
        existing = next((j for j in self.store.jobs(project["id"]) if j["status"] in ("queued", "rendering")), None)
        if existing:
            return existing
        job = {"id": uid(), "projectId": project["id"], "projectName": project["name"], "revision": project["revision"],
               "status": "queued", "progress": 0, "stage": "Waiting to render", "createdAt": now(), "error": None}
        self.store.put_job(job)
        # Immutable copies: edits made later do not change this job's inputs.
        self.executor.submit(self.run_render, json.loads(json.dumps(project)), dict(music), dict(job))
        return job

    def run_render(self, project, music, job):
        def report(progress, stage):
            job.update(status="rendering", progress=round(progress, 1), stage=stage)
            self.store.put_job(job)
        try:
            report(1, "Starting export")
            destination = self.store.directory / "exports" / (job["id"] + ".mp4")
            result = render_video(project, self.store.directory / "media" / music["storedName"], destination, report)
            job.update(status="complete", progress=100, stage="Ready to download", result=result, completedAt=now())
        except Exception as error:
            job.update(status="failed", stage="Export failed", error=str(error))
        self.store.put_job(job)


class Handler(BaseHTTPRequestHandler):
    server_version = "BreathworkStudio/0.4"

    def __init__(self, *args, application=None, **kwargs):
        self.application = application
        super().__init__(*args, **kwargs)

    @property
    def store(self):
        return self.application.store

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
        super().end_headers()

    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def log_message(self, format, *args):
        # Do not log URLs containing one-time values or request/credential bodies.
        super().log_message("%s %s", self.command, urlsplit(self.path).path)

    def read_chunk(self):
        size = int(self.headers.get("Content-Length", 0))
        if not 0 < size <= CHUNK_BYTES:
            raise ValidationError("Upload one chunk of at most 4 MB.")
        data = self.rfile.read(size)
        if len(data) != size:
            raise ValidationError("The chunk was interrupted. Resume the upload.")
        return data

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise ValidationError("This request needs JSON data.")
        size = int(self.headers.get("Content-Length", 0))
        if not 0 < size <= 25 * 1024 * 1024:
            raise ValidationError("Request size is invalid or too large.")
        return json.loads(self.rfile.read(size))

    def send_file(self, path, filename=None, content_type=None):
        path = Path(path)
        if not path.is_file():
            raise KeyError("File not found.")
        size = path.stat().st_size
        start, end = 0, size - 1
        partial_response = False
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                self.send_error(416)
                return
            if match[1]:
                start = int(match[1])
                if match[2]:
                    end = min(end, int(match[2]))
            else:
                start = max(0, size - int(match[2]))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            partial_response = True
        self.send_response(206 if partial_response else 200)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if partial_response:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = handle.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def guarded(self, action):
        try:
            route = urlsplit(self.path).path
            remote = self.application.remote
            expected = urlsplit(self.application.public_url).netloc if remote else self.headers.get("Host", "")
            if (remote and self.headers.get("Host", "").lower() != expected.lower()) or (not remote and urlsplit("http://" + expected).hostname not in ("127.0.0.1", "localhost")):
                raise AccessError("Use the configured address for this app.", 403)
            origin = self.headers.get("Origin")
            writing = self.command not in ("GET", "HEAD")
            if writing and origin and (urlsplit(origin).netloc != expected or (remote and origin != self.application.public_url)):
                raise AccessError("Open the app at its configured address to make changes.", 403)
            self.user = {"id": "local", "username": "Local workspace", "role": "owner"}
            if remote:
                public = route in ("/", "/login", "/login.js", "/styles.css", "/api/health", "/api/auth/state", "/api/auth/login", "/api/auth/setup", "/assets/Inter.ttf", "/assets/Inter-OFL.txt")
                if route.startswith("/api/worker/"):
                    self.worker_identity = self.application.security.worker(self.headers.get("Authorization", ""))
                elif not public:
                    self.user = self.application.security.session(self.headers.get("Cookie"))
                    if writing and not hmac.compare_digest(self.user["csrf"], self.headers.get("X-CSRF-Token", "")):
                        raise AccessError("Your session changed. Reload the page before making changes.", 403)
                    if route.startswith("/api/admin/") or (route == "/api/services" and writing):
                        if self.user["role"] != "owner":
                            raise AccessError("Only the owner can change these settings.", 403)
            elif route.startswith(("/api/worker/", "/api/admin/")):
                raise AccessError("This feature is available in server mode.", 403)
            action()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ConflictError as error:
            self.send_json({"error": str(error)}, 409)
        except AccessError as error:
            self.send_json({"error": str(error)}, error.status)
        except (ValidationError, ValueError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)
        except KeyError as error:
            self.send_json({"error": str(error).strip("'")}, 404)
        except Exception as error:
            self.log_error("%s", error)
            self.send_json({"error": "The app could not complete that request. Check the server log."}, 500)

    def do_GET(self):
        self.guarded(self.get_request)

    def get_request(self):
        url = urlsplit(self.path)
        route = url.path
        if route == "/api/health":
            self.send_json({"ready": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")), "version": RENDERER_VERSION, "mode": "server" if self.application.remote else "local", "protocol": PROTOCOL})
        elif route == "/api/auth/state":
            self.send_json({"remote": self.application.remote, "needsSetup": bool(self.application.security and self.application.security.needs_setup())})
        elif route == "/api/auth/me":
            self.send_json({**self.user, "remote": self.application.remote})
        elif route == "/api/admin/users":
            self.send_json(self.application.security.users())
        elif route == "/api/admin/workers":
            self.send_json(self.application.security.workers())
        elif route == "/api/worker/info":
            self.send_json({"protocol": PROTOCOL, "rendererVersion": RENDERER_VERSION, "worker": self.worker_identity})
        elif match := re.fullmatch(r"/api/worker/jobs/([a-z0-9]+)/music", route):
            self.send_file(self.application.queue.music(match[1], self.worker_identity["id"], self.headers.get("X-Render-Attempt", "")))
        elif route == "/api/services":
            self.send_json(self.application.drafts.settings.public())
        elif route == "/api/drafts":
            self.send_json(self.application.drafts.jobs())
        elif match := re.fullmatch(r"/api/drafts/([a-z0-9]+)/source", route):
            job = next((j for j in self.application.drafts.jobs(False) if j["id"] == match[1]), None)
            if not job or not job.get("source"):
                raise KeyError("The timed transcript is not ready yet.")
            self.send_json({"name": job["name"], "language": job["language"], "segments": job["source"]})
        elif route == "/api/projects":
            self.send_json(self.store.summaries())
        elif route == "/api/catalog":
            self.send_json([{**d["subtitle"], "displayLanguage": display_language(d["subtitle"]), "count": len(d["segments"])} for d in self.store.catalog])
        elif match := re.fullmatch(r"/api/archive/(\d+)", route):
            self.send_json(self.store.catalog_by_id[match[1]])
        elif match := re.fullmatch(r"/api/projects/([a-z0-9]+)", route):
            project = self.store.get(match[1])
            self.send_json({**project, "music": self.store.media(project["musicId"]) if project.get("musicId") else None})
        elif match := re.fullmatch(r"/api/projects/([a-z0-9]+)/subtitles\.(srt|vtt|json)", route):
            project, fmt = self.store.get(match[1]), match[2]
            content = json.dumps(project, ensure_ascii=False, indent=2) if fmt == "json" else subtitle_text(project, fmt)
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8" if fmt == "json" else "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(project["name"] + "." + fmt))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif match := re.fullmatch(r"/api/projects/([a-z0-9]+)/frame", route):
            project = normalize_project(self.store.get(match[1]))
            index = int(parse_qs(url.query).get("cue", ["0"])[0])
            if not 0 <= index < len(project["segments"]):
                raise ValidationError("Cue index is outside this session.")
            if project["style"]["layout"] == "teleprompter":
                from teleprompter import make_frame as presenter_frame
                duration = self.store.media(project["musicId"])["durationMs"] if project.get("musicId") else project["segments"][-1]["endMs"] + project["cueOffsetMs"]
                at_ms = int(parse_qs(url.query).get("timeMs", [project["segments"][index]["startMs"] + project["cueOffsetMs"]])[0])
                image = presenter_frame(project, at_ms, duration)
            else:
                image = make_frame(project, project["segments"][index]["text"])
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            body = buffer.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif route == "/api/jobs":
            self.send_json(self.application.queue.list(parse_qs(url.query).get("projectId", [None])[0]))
        elif match := re.fullmatch(r"/api/jobs/([a-z0-9]+)/download", route):
            job = next((j for j in self.store.jobs() if j["id"] == match[1]), None)
            if job is None:
                raise KeyError("Export not found.")
            if job["status"] != "complete":
                raise ValidationError("This export is not finished yet.")
            self.send_file(self.store.directory / "exports" / (job["id"] + ".mp4"), job["projectName"] + ".mp4")
        elif match := re.fullmatch(r"/media/([a-z0-9]+)(/waveform\.png)?", route):
            media = self.store.media(match[1])
            target = media["storedName"] if not match[2] else media["id"] + "-waveform.png"
            self.send_file(self.store.directory / "media" / target, content_type=media.get("mime") if not match[2] else "image/png")
        elif route in ("/", "/login", "/login.js", "/app.js", "/teleprompter.js", "/styles.css"):
            filename = "index.html" if route == "/" else "login.html" if route == "/login" else route[1:]
            if route == "/" and self.application.remote:
                try:
                    self.application.security.session(self.headers.get("Cookie"))
                except AccessError:
                    filename = "login.html"
            self.send_file(ROOT / "static" / filename)
        elif route in ("/assets/Inter.ttf", "/assets/Inter-OFL.txt"):
            self.send_file(ROOT / "static" / route[1:])
        else:
            raise KeyError("Page not found.")

    def do_POST(self):
        self.guarded(self.post_request)

    def post_request(self):
        route = urlsplit(self.path).path
        if route.startswith("/api/worker/"):
            return self.worker_request(route)
        if match := re.fullmatch(r"/api/uploads/([a-z0-9]+)/chunk", route):
            self.send_json(self.application.uploads.chunk(self.user["id"], match[1], int(self.headers.get("X-Upload-Offset", -1)), self.read_chunk()))
            return
        if route == "/api/media":
            if self.application.remote:
                raise ValidationError("Use resumable audio uploads in server mode.")
            purpose = self.headers.get("X-Media-Purpose", "music")
            if purpose not in ("music", "reference"):
                raise ValidationError("Choose music or source audio.")
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 4 * 1024 ** 3:
                raise ValidationError("Choose an audio file smaller than 4 GB.")
            media_id = uid()
            name = Path(unquote(self.headers.get("X-Filename", "music.mp3"))).name[:200]
            extension = Path(name).suffix.lower()
            if extension not in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aif", ".aiff", ".mp4"):
                raise ValidationError("Use MP3, WAV, M4A, AAC, FLAC, OGG, or AIFF audio.")
            stored_name = media_id + extension
            target = self.store.directory / "media" / stored_name
            try:
                with target.open("wb") as handle:
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValidationError("The upload was interrupted. Please try again.")
                        handle.write(chunk)
                        remaining -= len(chunk)
                information = probe_audio(target)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            media = {"id": media_id, "name": name, "storedName": stored_name, "purpose": purpose, "bytes": size, "mime": mimetypes.guess_type(name)[0] or "audio/mpeg", **information}
            self.store.put_media(media)
            self.send_json(media, 201)
            def waveform():
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(target), "-filter_complex", "aformat=channel_layouts=mono,aresample=2000,showwavespic=s=1600x100:colors=0x72a99d", "-frames:v", "1", str(target.with_name(media_id + "-waveform.png"))], capture_output=True, timeout=180)
            threading.Thread(target=waveform, daemon=True).start()
            return
        payload = self.read_json()
        if route in ("/api/auth/setup", "/api/auth/login"):
            security = self.application.security
            if not security:
                raise ValidationError("Sign-in is enabled only in server mode.")
            security.limit(self.client_address[0])
            if route.endswith("setup"):
                security.create_user(payload, setup=True)
            token, user = security.login(payload)
            self.send_response(200)
            body = json.dumps(user).encode()
            self.send_header("Set-Cookie", f"{security.COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=43200")
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif route == "/api/auth/logout":
            self.application.security.logout(self.headers.get("Cookie"))
            self.send_response(200)
            self.send_header("Set-Cookie", "studio_session=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
        elif route == "/api/admin/users":
            self.send_json(self.application.security.create_user(payload), 201)
        elif match := re.fullmatch(r"/api/admin/users/([a-z0-9]+)/disable", route):
            self.application.security.disable_user(match[1]); self.send_json({"ok": True})
        elif route == "/api/admin/workers":
            self.send_json(self.application.security.add_worker(payload.get("name")), 201)
        elif match := re.fullmatch(r"/api/admin/workers/([a-z0-9]+)/revoke", route):
            self.application.security.revoke_worker(match[1]); self.send_json({"ok": True})
        elif route == "/api/uploads":
            self.send_json(self.application.uploads.start(self.user["id"], payload), 201)
        elif match := re.fullmatch(r"/api/uploads/([a-z0-9]+)/finish", route):
            media = self.application.uploads.finish(self.user["id"], match[1])
            self.waveform(media)
            self.send_json(media, 201)
        elif match := re.fullmatch(r"/api/jobs/([a-z0-9]+)/(retry|cancel)", route):
            self.send_json(self.application.queue.action(match[1], match[2]))
        elif route == "/api/services":
            self.send_json(self.application.drafts.settings.save(payload))
        elif route == "/api/drafts":
            self.send_json(self.application.drafts.start(payload), 202)
        elif match := re.fullmatch(r"/api/drafts/([a-z0-9]+)/retry", route):
            self.send_json(self.application.drafts.retry(match[1]), 202)
        elif route == "/api/projects":
            self.send_json(self.store.create_from_archive(payload["subtitleId"]), 201)
        elif route == "/api/import":
            parsed = json.loads(payload["text"]) if payload["text"].lstrip("\ufeff \n\r\t").startswith("{") else None
            name = parsed.get("name") if isinstance(parsed, dict) else None
            source_id = parsed.get("sourceId") if isinstance(parsed, dict) else None
            if str(source_id) not in self.store.catalog_by_id:
                source_id = None
            reference = parsed.get("reference") if isinstance(parsed, dict) else None
            if reference:
                reference = {**reference, "mediaId": None}  # Audio is not embedded in a JSON backup.
            project = self.store.create(name or payload.get("name", "Imported session"), import_subtitles(payload["text"]), source_id, reference=reference)
            if isinstance(parsed, dict) and ("style" in parsed or "cueOffsetMs" in parsed):
                project.update(style=parsed.get("style", project["style"]), cueOffsetMs=parsed.get("cueOffsetMs", 0))
                project = self.store.save(project["id"], project)
            self.send_json(project, 201)
        elif match := re.fullmatch(r"/api/projects/([a-z0-9]+)/duplicate", route):
            old = self.store.get(match[1])
            project = self.store.create(old["name"] + " · copy", [{**s, "id": uid()} for s in old["segments"]], old.get("sourceId"), old.get("archiveId"), old.get("reference"))
            project.update(style=old["style"], cueOffsetMs=old["cueOffsetMs"], musicId=old.get("musicId"))
            self.send_json(self.store.save(project["id"], project), 201)
        elif match := re.fullmatch(r"/api/projects/([a-z0-9]+)/render", route):
            self.send_json(self.application.render(self.store.get(match[1]), payload["revision"]), 202)
        else:
            raise KeyError("Action not found.")

    def waveform(self, media):
        target = self.store.directory / "media" / media["storedName"]
        image = target.with_name(media["id"] + "-waveform.png")
        if image.exists():
            return
        def create():
            try:
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(target), "-filter_complex", "aformat=channel_layouts=mono,aresample=2000,showwavespic=s=1600x100:colors=0x72a99d", "-frames:v", "1", str(image)], capture_output=True, timeout=180)
            except subprocess.TimeoutExpired:
                pass
        threading.Thread(target=create, daemon=True).start()

    def worker_request(self, route):
        worker = self.worker_identity["id"]
        queue = self.application.queue
        if match := re.fullmatch(r"/api/worker/jobs/([a-z0-9]+)/chunk", route):
            self.send_json(queue.upload_chunk(match[1], worker, self.headers.get("X-Render-Attempt", ""), int(self.headers.get("X-Upload-Offset", -1)), self.read_chunk()))
            return
        payload = self.read_json()
        if route == "/api/worker/claim":
            request_id = str(payload.get("requestId", ""))
            if not re.fullmatch(r"[a-z0-9]{32}", request_id):
                raise ValidationError("A unique claim request ID is required.")
            self.send_json({"job": queue.claim(worker, payload.get("protocol"), payload.get("rendererVersion"), request_id)})
        elif match := re.fullmatch(r"/api/worker/jobs/([a-z0-9]+)/(heartbeat|release|fail|upload|complete)", route):
            job_id, action = match.groups()
            if action == "heartbeat":
                result = queue.heartbeat(job_id, worker, payload)
            elif action in ("release", "fail"):
                result = queue.finish_attempt(job_id, worker, payload, release=action == "release")
            elif action == "upload":
                result = queue.start_upload(job_id, worker, payload)
            else:
                result = queue.complete(job_id, worker, payload)
            self.send_json(result)
        else:
            raise KeyError("Worker action not found.")

    def do_PUT(self):
        def update():
            match = re.fullmatch(r"/api/projects/([a-z0-9]+)", urlsplit(self.path).path)
            if not match:
                raise KeyError("Session not found.")
            self.send_json(self.store.save(match[1], self.read_json()))
        self.guarded(update)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--bind", default=os.environ.get("STUDIO_BIND", "127.0.0.1"))
    parser.add_argument("--mode", choices=("local", "server"), default=os.environ.get("STUDIO_MODE", "local"))
    parser.add_argument("--public-url", default=os.environ.get("STUDIO_PUBLIC_URL"))
    parser.add_argument("--open", action="store_true", help="Open the app in your normal browser after starting")
    options = parser.parse_args()
    if options.mode == "local" and options.bind not in ("127.0.0.1", "localhost"):
        parser.error("Use server mode with sign-in when listening beyond localhost.")
    os.umask(0o077)
    application = Application(options.data, options.mode == "server", options.public_url)
    server = ThreadingHTTPServer((options.bind, options.port), partial(Handler, application=application))
    print(f"Breathwork Studio is ready: {application.public_url or f'http://127.0.0.1:{options.port}'}", flush=True)
    if application.security and application.security.needs_setup():
        print("First-time setup code: " + (options.data / "setup-code").read_text().strip(), flush=True)
    if options.open:
        import webbrowser
        threading.Timer(.5, lambda: webbrowser.open(f"http://127.0.0.1:{options.port}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.executor.shutdown(wait=False, cancel_futures=True)
        application.drafts.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
