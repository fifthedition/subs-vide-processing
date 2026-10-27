"""Queue recovery, access boundaries, transfers and a real HTTP worker round trip."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import unquote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app import Application, Handler
from export_queue import ExportQueue, PROTOCOL, RENDERER_VERSION, file_hash
from security import Security, AccessError
from studio import Store, ConflictError, ValidationError, render_video
from uploads import Uploads
from test_studio import synthetic_audio, test_project
from worker import drain, WorkerError


def session_with_music(store):
    project = store.create("Queue example", test_project()["segments"])
    project.update(cueOffsetMs=1000, style=test_project()["style"])
    path = store.directory / "media/music.wav"
    synthetic_audio(path)
    media = {"id": "music", "storedName": "music.wav", "name": "Music.wav", "purpose": "music", "durationMs": 8000, "bytes": path.stat().st_size, "sha256": file_hash(path)}
    store.put_media(media)
    project["musicId"] = "music"
    return store.save(project["id"], project)


class QueueTests(unittest.TestCase):
    def test_manual_worker_continues_after_failure_and_releases_on_control_c(self):
        class FakeClient:
            def __init__(self):
                self.calls = []
                self.claims = iter([{"id": "first", "attempt": "a", "project": {"name": "First", "revision": 1}},
                                    {"id": "second", "attempt": "b", "project": {"name": "Second", "revision": 2}}, None])
            def request(self, route, payload, **kwargs):
                self.calls.append(route)
                return {"job": next(self.claims)} if route.endswith("/claim") else {"ok": True}
        client = FakeClient()
        with patch("worker.process_job", side_effect=[WorkerError("Example failure"), None]), patch("sys.stdout", new=io.StringIO()) as output:
            self.assertEqual(drain(client, Path("unused")), 1)
            self.assertIn("1 video(s) uploaded; 1 failed", output.getvalue())
        self.assertIn("/api/worker/jobs/first/fail", client.calls)
        client = FakeClient()
        with patch("worker.process_job", side_effect=KeyboardInterrupt), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(drain(client, Path("unused")), 130)
        self.assertEqual(client.calls[-1], "/api/worker/jobs/first/release")

    def test_video_chunks_resume_and_completion_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            project = session_with_music(store)
            queue = ExportQueue(store)
            queue.enqueue(project, project["revision"])
            job = queue.claim("mac", PROTOCOL, RENDERER_VERSION)
            video = Path(directory) / "render.mp4"
            render_video(job["project"], Path(directory) / "media/music.wav", video)
            data = video.read_bytes()
            upload = {"attempt": job["attempt"], "bytes": len(data), "sha256": file_hash(video)}
            self.assertEqual(queue.start_upload(job["id"], "mac", upload)["offset"], 0)
            queue.upload_chunk(job["id"], "mac", job["attempt"], 0, data[:1000])
            self.assertEqual(queue.start_upload(job["id"], "mac", upload)["offset"], 1000)
            self.assertEqual(queue.upload_chunk(job["id"], "mac", job["attempt"], 0, data[:1000])["offset"], 1000)
            with self.assertRaises(ConflictError):
                queue.upload_chunk(job["id"], "mac", job["attempt"], 0, b"mismatch")
            with self.assertRaises(ValidationError):
                queue.complete(job["id"], "mac", {"attempt": job["attempt"]})
            queue.upload_chunk(job["id"], "mac", job["attempt"], 1000, data[1000:])
            completed = queue.complete(job["id"], "mac", {"attempt": job["attempt"]})
            self.assertEqual(completed["status"], "complete")
            self.assertEqual(queue.complete(job["id"], "mac", {"attempt": job["attempt"]}), completed)
            self.assertEqual(file_hash(Path(directory) / "exports" / (job["id"] + ".mp4")), upload["sha256"])

    def test_snapshot_deduplication_restart_and_atomic_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            project = session_with_music(store)
            queue = ExportQueue(store)
            first = queue.enqueue(project, project["revision"])
            self.assertEqual(queue.enqueue(project, project["revision"])["id"], first["id"])
            for private in ("snapshot", "music", "attempt", "workerId"):
                self.assertNotIn(private, first)
            project["segments"][0]["text"] = "Edited after submission"
            store.save(project["id"], project)
            restarted = ExportQueue(Store(directory))
            self.assertEqual(restarted.list()[0]["status"], "queued")
            with ThreadPoolExecutor(max_workers=2) as executor:
                claims = list(executor.map(lambda worker: restarted.claim(worker, PROTOCOL, RENDERER_VERSION, worker), ["mac1", "mac2"]))
            self.assertEqual(sum(job is not None for job in claims), 1)
            claim = next(job for job in claims if job)
            self.assertNotEqual(claim["project"]["segments"][0]["text"], "Edited after submission")
            self.assertEqual(ExportQueue(Store(directory)).list()[0]["status"], "rendering")

    def test_expired_claim_is_requeued_and_old_result_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            queue = ExportQueue(store)
            project = session_with_music(store)
            queued = queue.enqueue(project, project["revision"])
            claim = queue.claim("mac", PROTOCOL, RENDERER_VERSION, "request")
            self.assertEqual(queue.claim("mac", PROTOCOL, RENDERER_VERSION, "request")["attempt"], claim["attempt"])
            with self.assertRaises(ConflictError):
                queue.claim("mac", PROTOCOL, RENDERER_VERSION, "another")
            job = store.jobs()[0]
            job["leaseUntil"] = time.time() - 1
            store.put_job(job)
            second = queue.claim("mac", PROTOCOL, RENDERER_VERSION, "next")
            self.assertEqual(second["id"], queued["id"])
            self.assertNotEqual(second["attempt"], claim["attempt"])
            with self.assertRaises(ConflictError):
                queue.heartbeat(claim["id"], "mac", {"attempt": claim["attempt"], "progress": 99})
            queue.finish_attempt(second["id"], "mac", {"attempt": second["attempt"], "error": "Example failure"})
            self.assertEqual(queue.list()[0]["status"], "failed")
            queue.action(second["id"], "retry")
            self.assertEqual(queue.list()[0]["status"], "queued")
            queue.action(second["id"], "cancel")
            self.assertIsNone(queue.claim("mac", PROTOCOL, RENDERER_VERSION))

    def test_preflight_and_version_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            project = session_with_music(store)
            queue = ExportQueue(store)
            with self.assertRaises(ConflictError):
                queue.enqueue(project, 99)
            with self.assertRaises(ConflictError):
                queue.claim("mac", PROTOCOL, "old")
            project["segments"][-1]["endMs"] = 9000
            with self.assertRaisesRegex(ValidationError, "final prompt"):
                queue.enqueue(project, project["revision"])
            project["segments"][-1]["endMs"] = 5000
            project["segments"][0]["text"] = ""
            with self.assertRaisesRegex(ValidationError, "empty prompts"):
                queue.enqueue(project, project["revision"])


class AccountAndUploadTests(unittest.TestCase):
    def test_setup_sessions_password_hashes_and_revocable_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            security = Security(store)
            self.assertTrue(security.needs_setup())
            payload = {"code": (Path(directory) / "setup-code").read_text(), "username": "owner", "password": "example-long-password"}
            security.create_user(payload, setup=True)
            self.assertFalse((Path(directory) / "setup-code").exists())
            with self.assertRaises(AccessError):
                security.create_user(payload, setup=True)
            token, owner = security.login(payload)
            self.assertEqual(security.session("studio_session=" + token)["role"], "owner")
            self.assertNotIn(payload["password"].encode(), store.database.read_bytes())
            worker = security.add_worker("Mac")
            self.assertEqual(security.worker("Bearer " + worker["token"])["id"], worker["id"])
            self.assertNotIn(worker["token"], json.dumps(security.workers()))
            security.revoke_worker(worker["id"])
            with self.assertRaises(AccessError):
                security.worker("Bearer " + worker["token"])
            editor = security.create_user({"username": "editor", "password": "another-long-password"})
            editor_token, _ = security.login({"username": "editor", "password": "another-long-password"})
            security.disable_user(editor["id"])
            with self.assertRaises(AccessError):
                security.session("studio_session=" + editor_token)
            security.logout("studio_session=" + token)
            with self.assertRaises(AccessError):
                security.session("studio_session=" + token)

    def test_audio_upload_resume_duplicate_chunk_finish_and_owner_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            uploads = Uploads(store)
            audio = Path(directory) / "sample.wav"
            synthetic_audio(audio, .3)
            data = audio.read_bytes()
            payload = {"name": "sample.wav", "purpose": "music", "bytes": len(data), "key": "sample-fingerprint"}
            item = uploads.start("editor1", payload)
            uploads.chunk("editor1", item["id"], 0, data[:1000])
            self.assertEqual(Uploads(Store(directory)).start("editor1", payload)["offset"], 1000)
            self.assertEqual(uploads.chunk("editor1", item["id"], 0, data[:1000])["offset"], 1000)
            with self.assertRaises(ConflictError):
                uploads.chunk("editor1", item["id"], 0, b"different")
            with self.assertRaises(KeyError):
                uploads.chunk("editor2", item["id"], 1000, data[1000:])
            uploads.chunk("editor1", item["id"], 1000, data[1000:])
            media = uploads.finish("editor1", item["id"])
            self.assertEqual(media["sha256"], file_hash(audio))
            self.assertEqual(media, uploads.finish("editor1", item["id"]))
            self.assertEqual(uploads.start("editor1", payload)["media"], media)


class HTTPWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.app = Application(self.directory / "nas", remote=True, public_url="https://127.0.0.1")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, application=self.app))
        self.port = self.server.server_port
        self.app.public_url = f"https://127.0.0.1:{self.port}"
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.cookie = ""
        self.csrf = ""
        payload = {"code": (self.directory / "nas/setup-code").read_text(), "username": "owner", "password": "owner-example-password"}
        response, self.owner = self.request("/api/auth/setup", payload)
        self.cookie = response.headers["Set-Cookie"].split(";")[0]
        self.csrf = self.owner["csrf"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.executor.shutdown(wait=True)
        self.app.drafts.executor.shutdown(wait=True)
        self.temp.cleanup()

    def request(self, route, body=None, headers=None):
        request = Request(self.base + route, data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Cookie": self.cookie, "X-CSRF-Token": self.csrf, **(headers or {})})
        with urlopen(request, timeout=30) as response:
            data = response.read()
            return response, json.loads(data) if response.headers.get_content_type() == "application/json" else data

    def test_http_auth_role_csrf_and_renderer_scope(self):
        for headers in ({"Cookie": ""}, {"Cookie": "studio_session=invalid"}):
            with self.assertRaises(HTTPError) as error:
                self.request("/api/projects", headers=headers)
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.request("/api/admin/users", {"username": "editor", "password": "editor-example-password"}, {"X-CSRF-Token": ""})
        self.assertEqual(error.exception.code, 403);error.exception.close()
        _, editor = self.request("/api/admin/users", {"username": "editor", "password": "editor-example-password"})
        response, editor_login = self.request("/api/auth/login", {"username": "editor", "password": "editor-example-password"})
        editor_headers = {"Cookie": response.headers["Set-Cookie"].split(";")[0], "X-CSRF-Token": editor_login["csrf"]}
        self.assertIn("Secure; HttpOnly; SameSite=Strict", response.headers["Set-Cookie"])
        with self.assertRaises(HTTPError) as error:
            self.request("/api/admin/workers", {"name": "Forbidden"}, editor_headers)
        self.assertEqual(error.exception.code, 403);error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.request("/api/services", {"elevenlabs": "forbidden"}, editor_headers)
        self.assertEqual(error.exception.code, 403);error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.request("/api/import", {"text": "{}"}, {"Origin": "https://another.example"})
        self.assertEqual(error.exception.code, 403);error.exception.close()
        _, worker = self.request("/api/admin/workers", {"name": "Mac"})
        with self.assertRaises(HTTPError) as error:
            self.request("/api/projects", headers={"Cookie": "", "Authorization": "Bearer " + worker["token"]})
        self.assertEqual(error.exception.code, 401);error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.request("/api/projects", headers={"Host": "evil.example"})
        self.assertEqual(error.exception.code, 403);error.exception.close()

    def test_real_worker_exits_after_render_upload_and_empty_queue(self):
        project = session_with_music(self.app.store)
        _, job = self.request("/api/projects/" + project["id"] + "/render", {"revision": project["revision"]})
        _, worker = self.request("/api/admin/workers", {"name": "Test renderer"})
        token_file = self.directory / "worker-token"
        token_file.write_text(worker["token"])
        os.chmod(token_file, 0o600)
        command = [sys.executable, "worker.py", "--url", self.base, "--token-file", str(token_file), "--cache", str(self.directory / "mac"), "--allow-local-test"]
        process = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=45)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("Queue empty. 1 video(s) uploaded; 0 failed. Renderer stopped.", process.stdout)
        _, jobs = self.request("/api/jobs")
        self.assertEqual(jobs[0]["status"], "complete")
        for private in ("snapshot", "attempt", "workerId", "claimId"):
            self.assertNotIn(private, jobs[0])
        response, video = self.request("/api/jobs/" + job["id"] + "/download?timezone=Europe%2FCopenhagen")
        self.assertEqual(len(video), jobs[0]["result"]["bytes"])
        filename = unquote(response.headers["Content-Disposition"])
        exported_at = datetime.fromisoformat(jobs[0]["completedAt"]).astimezone(ZoneInfo("Europe/Copenhagen"))
        self.assertIn(f"_r{project['revision']}_", filename)
        self.assertIn(exported_at.strftime("%Y-%m-%d_%H-%M-%S%z"), filename)
        self.assertTrue(filename.endswith(job["id"][:8] + ".mp4"))
        response, first_byte = self.request("/api/jobs/" + job["id"] + "/download", headers={"Range": "bytes=0-0"})
        self.assertEqual(first_byte, video[:1])
        self.assertIn("+0000", unquote(response.headers["Content-Disposition"]))
        self.assertEqual(list((self.directory / "mac/exports").iterdir()), [])
        second = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
        self.assertEqual(second.returncode, 0)
        self.assertIn("Queue empty. 0 video(s) uploaded", second.stdout)


if __name__ == "__main__":
    unittest.main()
