"""Durable immutable exports. Every mutation checks the current claim attempt."""
import copy
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from studio import ConflictError, ValidationError, make_frame, normalize_project, now, uid

PROTOCOL = 1
RENDERER_VERSION = "0.5.0"
LEASE_SECONDS = 180
CHUNK_BYTES = 4 * 1024 * 1024
MAX_EXPORT_BYTES = 32 * 1024 ** 3


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def public_job(job):
    return {key: value for key, value in job.items() if key not in ("snapshot", "music", "attempt", "workerId", "leaseUntil", "upload", "claimId")}


def export_filename(job, time_zone="UTC"):
    """Name a download by saved revision and export time in the viewer's zone."""
    try:
        zone = ZoneInfo(time_zone) if isinstance(time_zone, str) and len(time_zone) <= 100 else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    timestamp = None
    for value in (job.get("completedAt"), job.get("createdAt")):
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
            break
        except ValueError:
            continue
    stamp = timestamp.astimezone(zone).strftime("%Y-%m-%d_%H-%M-%S%z") if timestamp else "undated"
    name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]+', "-", str(job.get("projectName") or "Session")).strip(" .")
    name = name.encode("utf-8")[:120].decode("utf-8", errors="ignore").rstrip(" .") or "Session"
    identifier = re.sub(r"[^a-zA-Z0-9]", "", str(job["id"]))[:8]
    return f"{name}_r{job['revision']}_{stamp}_{identifier}.mp4"


class ExportQueue:
    def __init__(self, store):
        self.store = store
        self.temporary = store.directory / "render-uploads"
        self.temporary.mkdir(exist_ok=True)

    @staticmethod
    def _get(db, job_id):
        row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError("Export not found.")
        return json.loads(row[0])

    @staticmethod
    def _put(db, job):
        db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?)", (job["id"], json.dumps(job, ensure_ascii=False)))

    def enqueue(self, project, revision):
        if project["revision"] != revision:
            raise ConflictError("Save your current changes before sending this session for export.")
        project = normalize_project(project)
        if not project.get("musicId") or not project["segments"]:
            raise ValidationError("Add your music-only track and at least one Slovak prompt first.")
        music = self.store.media(project["musicId"])
        path = self.store.directory / "media" / music["storedName"]
        if music.get("purpose") == "reference":
            raise ValidationError("Use the separate music-only track for export.")
        if not path.is_file():
            raise ValidationError("The music file is missing. Upload it again.")
        offset = project["cueOffsetMs"]
        if project["segments"][0]["startMs"] + offset < 0:
            raise ValidationError("The first prompt starts before the music. Adjust the prompt offset.")
        if project["segments"][-1]["endMs"] + offset > music["durationMs"] + 50:
            raise ValidationError("The final prompt ends after the music. Adjust its timing.")
        if any(not cue["text"].strip() for cue in project["segments"]):
            raise ValidationError("Fill or remove empty prompts before sending for export.")
        # Check each cue in all three areas, without allocating render frames on disk.
        if project["style"]["layout"] == "teleprompter":
            from teleprompter import make_body
            for index in range(len(project["segments"])):
                make_body(project, {"previous": index - 1, "current": index, "next": index + 1 if index + 1 < len(project["segments"]) else -1})
        else:
            for cue in project["segments"]:
                make_frame(project, cue["text"])
        music = {**music, "sha256": music.get("sha256") or file_hash(path)}
        snapshot = {key: copy.deepcopy(project[key]) for key in ("id", "name", "revision", "segments", "cueOffsetMs", "style")}
        job = {"id": uid(), "projectId": project["id"], "projectName": project["name"], "revision": revision,
               "status": "queued", "progress": 0, "stage": "Queued — waiting for renderer", "createdAt": now(),
               "error": None, "protocol": PROTOCOL, "rendererVersion": RENDERER_VERSION, "snapshot": snapshot, "music": music}
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Serialize double clicks, separate editor tabs and saves during preflight.
            row = db.execute("SELECT revision FROM projects WHERE id=?", (project["id"],)).fetchone()
            if not row or row[0] != revision:
                raise ConflictError("This session changed during export checks. Save and send it again.")
            for previous in (json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs")):
                if previous["projectId"] == project["id"] and previous["status"] in ("queued", "rendering"):
                    return public_job(previous)
            self._put(db, job)
        return public_job(job)

    def list(self, project_id=None):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            jobs = [json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs")]
        return [public_job(j) for j in sorted(jobs, key=lambda j: j["createdAt"], reverse=True) if project_id is None or j["projectId"] == project_id]

    def _expire(self, db):
        for row in db.execute("SELECT payload FROM jobs").fetchall():
            job = json.loads(row[0])
            if job.get("protocol") and job["status"] == "rendering" and job.get("leaseUntil", 0) < time.time():
                if job.get("attempt"):
                    (self.temporary / (job["id"] + "-" + job["attempt"])).unlink(missing_ok=True)
                job.update(status="queued", progress=0, stage="Queued — previous renderer disconnected", error=None)
                for key in ("attempt", "workerId", "leaseUntil", "upload", "claimId"):
                    job.pop(key, None)
                self._put(db, job)

    def claim(self, worker_id, protocol, renderer_version, request_id=None):
        if protocol != PROTOCOL or renderer_version != RENDERER_VERSION:
            raise ConflictError("Update the Mac renderer to match the NAS app (version " + RENDERER_VERSION + ").")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            jobs = sorted((json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs")), key=lambda j: j["createdAt"])
            active = next((j for j in jobs if j.get("workerId") == worker_id and j["status"] == "rendering"), None)
            if active and request_id and active.get("claimId") == request_id:
                return self.claim_payload(active)
            if active:
                raise ConflictError("This renderer still has an active claim. Wait up to three minutes after an interrupted run, then try again.")
            job = next((j for j in jobs if j["status"] == "queued" and j.get("protocol") == PROTOCOL and j.get("rendererVersion") == RENDERER_VERSION), None)
            if not job:
                if any(j["status"] == "queued" and j.get("protocol") for j in jobs):
                    raise ConflictError("Queued exports request another renderer version. Cancel and resubmit them after reviewing the app update.")
                return None
            job.update(status="rendering", progress=0, stage="Renderer connected", workerId=worker_id,
                       attempt=secrets.token_hex(16), leaseUntil=time.time() + LEASE_SECONDS, claimId=request_id, error=None)
            self._put(db, job)
        return self.claim_payload(job)

    @staticmethod
    def claim_payload(job):
        return {"id": job["id"], "attempt": job["attempt"], "project": job["snapshot"], "music": job["music"],
                "leaseSeconds": LEASE_SECONDS, "chunkBytes": CHUNK_BYTES}

    def checked(self, db, job_id, worker_id, attempt, complete_ok=False):
        job = self._get(db, job_id)
        if not job.get("attempt") or not hmac.compare_digest(job["attempt"], str(attempt)) or job.get("workerId") != worker_id:
            raise ConflictError("This render attempt is no longer active.")
        if complete_ok and job["status"] == "complete":
            return job
        if job["status"] != "rendering" or job.get("leaseUntil", 0) < time.time():
            raise ConflictError("The renderer lease expired. Start the worker again to reclaim the job.")
        return job

    def heartbeat(self, job_id, worker_id, payload):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.checked(db, job_id, worker_id, payload.get("attempt"))
            progress = float(payload.get("progress", job["progress"]))
            if not 0 <= progress <= 100:
                raise ValidationError("Invalid progress.")
            job.update(leaseUntil=time.time() + LEASE_SECONDS, progress=round(progress, 1), stage=str(payload.get("stage", job["stage"]))[:200])
            self._put(db, job)
        return {"ok": True}

    def music(self, job_id, worker_id, attempt):
        with self.store.connection() as db:
            job = self.checked(db, job_id, worker_id, attempt)
        return self.store.directory / "media" / job["music"]["storedName"]

    def finish_attempt(self, job_id, worker_id, payload, release=False):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.checked(db, job_id, worker_id, payload.get("attempt"))
            (self.temporary / (job_id + "-" + job["attempt"])).unlink(missing_ok=True)
            job.update(status="queued" if release else "failed", progress=0,
                       stage="Queued — waiting for renderer" if release else "Export failed",
                       error=None if release else str(payload.get("error", "The renderer could not complete this export."))[:1200])
            for key in ("attempt", "workerId", "leaseUntil", "upload", "claimId"):
                job.pop(key, None)
            self._put(db, job)
        return public_job(job)

    def action(self, job_id, action):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self._get(db, job_id)
            if action == "retry" and job["status"] == "failed" and job.get("protocol"):
                active = any(json.loads(r[0])["status"] in ("queued", "rendering") for r in db.execute("SELECT payload FROM jobs WHERE id<>?", (job_id,)) if json.loads(r[0])["projectId"] == job["projectId"])
                if active:
                    raise ConflictError("This session already has an active export.")
                job.update(status="queued", progress=0, stage="Queued — waiting for renderer", error=None)
            elif action == "cancel" and job["status"] == "queued":
                job.update(status="cancelled", stage="Export cancelled")
            else:
                raise ConflictError("That action is not available for this export.")
            self._put(db, job)
        return public_job(job)

    def start_upload(self, job_id, worker_id, payload):
        size, sha = int(payload.get("bytes", 0)), str(payload.get("sha256", ""))
        if not 0 < size <= MAX_EXPORT_BYTES or not re.fullmatch("[0-9a-f]{64}", sha):
            raise ValidationError("Invalid export size or SHA-256 digest.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.checked(db, job_id, worker_id, payload.get("attempt"))
            target = self.temporary / (job_id + "-" + job["attempt"])
            if job.get("upload") != {"bytes": size, "sha256": sha}:
                if shutil.disk_usage(self.temporary).free < size + 512 * 1024 ** 2:
                    raise ValidationError("The NAS needs more free space for this export.")
                target.unlink(missing_ok=True)
                job["upload"] = {"bytes": size, "sha256": sha}
            target.touch(exist_ok=True)
            self._put(db, job)
        return {"offset": target.stat().st_size, "chunkBytes": CHUNK_BYTES}

    def upload_chunk(self, job_id, worker_id, attempt, offset, data):
        if not 0 < len(data) <= CHUNK_BYTES:
            raise ValidationError("Upload one chunk of at most 4 MB.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.checked(db, job_id, worker_id, attempt)
            target = self.temporary / (job_id + "-" + job["attempt"])
            if not job.get("upload") or not target.exists():
                raise ConflictError("Start the export upload first.")
            if offset < 0 or offset > target.stat().st_size or offset + len(data) > job["upload"]["bytes"]:
                raise ConflictError("Resume at the server's upload offset.")
            with target.open("r+b") as handle:
                if offset < target.stat().st_size:
                    handle.seek(offset)
                    if handle.read(len(data)) != data:
                        raise ConflictError("This chunk does not match the saved export.")
                else:
                    handle.seek(offset)
                    handle.write(data)
                    handle.flush()
            return {"offset": target.stat().st_size}

    def complete(self, job_id, worker_id, payload):
        with self.store.connection() as db:
            job = self.checked(db, job_id, worker_id, payload.get("attempt"), complete_ok=True)
        if job["status"] == "complete":
            return public_job(job)
        target = self.temporary / (job_id + "-" + job["attempt"])
        destination = self.store.directory / "exports" / (job_id + ".mp4")
        candidate = target if target.exists() else destination
        upload = job.get("upload", {})
        if not candidate.is_file() or candidate.stat().st_size != upload.get("bytes") or file_hash(candidate) != upload.get("sha256"):
            raise ValidationError("The exported video upload is incomplete or failed its integrity check.")
        process = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(candidate)], capture_output=True, timeout=60)
        try:
            info = json.loads(process.stdout)
            duration = round(float(info["format"]["duration"]) * 1000)
            if process.returncode or sorted(s["codec_type"] for s in info["streams"]) != ["audio", "video"] or abs(duration - job["music"]["durationMs"]) > 250:
                raise ValueError()
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
            if job.get("rendererVersion") == RENDERER_VERSION and ((video.get("width"), video.get("height")) != (1920, 1080) or audio.get("channels") != 2):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ValidationError("The uploaded file is not a complete music-and-video export.") from None
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.checked(db, job_id, worker_id, payload.get("attempt"), complete_ok=True)
            if job["status"] == "complete":
                return public_job(job)
            if candidate != destination:
                candidate.replace(destination)
            job.update(status="complete", progress=100, stage="Ready to download", completedAt=now(),
                       result={"bytes": upload["bytes"], "sha256": upload["sha256"], "durationMs": duration})
            self._put(db, job)
        return public_job(job)
