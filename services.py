"""Optional server-side ElevenLabs transcription and DeepL Slovak drafting.

No provider request is made until a draft is explicitly started. Credentials
never enter a project, job response, subtitle backup, or diagnostic message.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
import copy
import json
import math
import os
import re
import socket
import subprocess
import tempfile
import threading

from studio import ConflictError, ValidationError, import_subtitles, normalize_segments, now, uid


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward a provider credential to another host.


def request_json(request, provider, timeout=180):
    try:
        with build_opener(NoRedirect).open(request, timeout=timeout) as response:
            data = response.read(50 * 1024 * 1024 + 1)
        if len(data) > 50 * 1024 * 1024:
            raise ValidationError(f"{provider} returned an unexpectedly large response.")
        return json.loads(data)
    except HTTPError as error:
        error.close()
        detail = {401: "Check your API key.", 403: "Check your key and API permissions.",
                  429: "The service is busy or your rate limit was reached.",
                  456: "Your translation quota has been reached."}.get(error.code, "Check your account or try again later.")
        raise ValidationError(f"{provider} returned HTTP {error.code}. {detail}") from None
    except (URLError, TimeoutError, socket.timeout, OSError):
        raise ValidationError(f"Could not reach {provider}, or the request timed out. No automatic retry was made.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationError(f"{provider} returned an unreadable response.") from None


class ServiceSettings:
    ENV = {"elevenlabs": "ELEVENLABS_API_KEY", "deepl": "DEEPL_AUTH_KEY"}

    def __init__(self, directory):
        self.path = Path(directory) / "services.json"
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            return json.loads(self.path.read_text()) if self.path.exists() else {}

    def key(self, provider):
        return os.environ.get(self.ENV[provider], "").strip() or self.read().get(provider, "")

    def public(self):
        return {p: {"configured": bool(self.key(p)), "fromEnvironment": bool(os.environ.get(env, "").strip())}
                for p, env in self.ENV.items()}

    def save(self, payload):
        with self.lock:
            values = self.read()
            for provider, env in self.ENV.items():
                value = payload.get(provider, "")
                if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 for c in value):
                    raise ValidationError("Enter a valid API key.")
                if payload.get("remove_" + provider):
                    values.pop(provider, None)
                elif value.strip():
                    values[provider] = value.strip()
            # Atomic replacement, restricted to this macOS/Linux user.
            fd, temporary = tempfile.mkstemp(prefix="services-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(values, handle)
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return self.public()


def scribe_cues(result):
    """Group word times into readable phrases, retaining actual silent gaps."""
    words = []
    for item in result.get("words", []):
        if item.get("type") != "word" or not str(item.get("text", "")).strip():
            continue
        try:
            start, end = float(item["start"]), float(item["end"])
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ValidationError("The transcript contains invalid word timestamps.") from None
        words.append({"startMs": round(start * 1000), "endMs": max(round(end * 1000), round(start * 1000) + 1), "text": str(item["text"]).strip()})
    words.sort(key=lambda word: word["startMs"])
    if not words:
        raise ValidationError("No timed speech was found. Choose a recording that contains the guide's voice.")
    cues, group = [], []

    def finish():
        text = " ".join(w["text"] for w in group)
        text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
        cues.append({"id": uid(), "startMs": group[0]["startMs"], "endMs": max(w["endMs"] for w in group), "text": text})

    for word in words:
        if group and (word["startMs"] - group[-1]["endMs"] >= 800 or
                      word["endMs"] - group[0]["startMs"] > 8000 or
                      sum(len(w["text"]) + 1 for w in group) + len(word["text"]) > 160 or
                      (re.search(r"[.!?…][\"'’”]*$", group[-1]["text"]) and group[-1]["endMs"] - group[0]["startMs"] >= 1500)):
            finish()
            group = []
        group.append(word)
    finish()
    # Word alignment can overlap slightly at phrase boundaries.
    for previous, following in zip(cues, cues[1:]):
        previous["endMs"] = min(previous["endMs"], following["startMs"])
    return normalize_segments(cues)


def transcribe(path, key, language, report):
    report(5, "Preparing source audio")
    with tempfile.TemporaryDirectory(prefix="scribe-") as directory:
        audio = Path(directory) / "source.mp3"
        process = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
            "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(audio)],
            capture_output=True, timeout=900)
        if process.returncode:
            raise ValidationError("The source recording could not be prepared for transcription.")
        boundary = "breathwork" + uid()
        fields = {"model_id": "scribe_v2", "timestamps_granularity": "word", "tag_audio_events": "false", "diarize": "false"}
        if language != "auto":
            fields["language_code"] = language
        prefix = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n' for name, value in fields.items())
        prefix += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="source.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'
        prefix, suffix = prefix.encode(), f"\r\n--{boundary}--\r\n".encode()

        def chunks():
            yield prefix
            with audio.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    yield chunk
            yield suffix

        report(15, "Transcribing with ElevenLabs · this may take several minutes")
        request = Request("https://api.elevenlabs.io/v1/speech-to-text", data=chunks(),
            headers={"xi-api-key": key, "Content-Type": "multipart/form-data; boundary=" + boundary,
                     "Content-Length": str(len(prefix) + audio.stat().st_size + len(suffix))}, method="POST")
        return request_json(request, "ElevenLabs", timeout=1800)


def translate_batch(texts, key, context):
    endpoint = "https://api-free.deepl.com/v2/translate" if key.endswith(":fx") else "https://api.deepl.com/v2/translate"
    payload = {"text": texts, "target_lang": "SK", "preserve_formatting": True, "context": context}
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    if len(encoded) >= 128 * 1024:
        raise ValidationError("A translation batch exceeds DeepL's request size limit.")
    result = request_json(Request(endpoint, data=encoded, method="POST",
        headers={"Authorization": "DeepL-Auth-Key " + key, "Content-Type": "application/json"}), "DeepL")
    values = result.get("translations")
    if not isinstance(values, list) or len(values) != len(texts) or any(not isinstance(t, dict) or not isinstance(t.get("text"), str) or not t["text"].strip() for t in values):
        raise ValidationError("DeepL returned an incomplete translation. Your source text and timings are preserved.")
    return [value["text"] for value in values]


class DraftService:
    def __init__(self, store):
        self.store = store
        self.settings = ServiceSettings(store.directory)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="subtitle-draft")
        self.lock = threading.RLock()
        (store.directory / "transcripts").mkdir(exist_ok=True)
        with store.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,payload TEXT)")
            for row in db.execute("SELECT id,payload FROM drafts").fetchall():
                job = json.loads(row["payload"])
                if job["status"] in ("queued", "working"):
                    job.update(status="failed", stage="Draft interrupted", error="The app stopped. Saved transcript and translation batches are retained.")
                    db.execute("UPDATE drafts SET payload=? WHERE id=?", (json.dumps(job), row["id"]))

    def put(self, job):
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO drafts VALUES(?,?)", (job["id"], json.dumps(job, ensure_ascii=False)))

    def jobs(self, public=True):
        with self.store.connection() as db:
            jobs = [json.loads(r[0]) for r in db.execute("SELECT payload FROM drafts")]
        jobs.sort(key=lambda j: j["createdAt"], reverse=True)
        return [self.public(j) for j in jobs] if public else jobs

    def public(self, job):
        return {k: v for k, v in job.items() if k not in ("source", "translated", "style", "cueOffsetMs", "musicId") } | {
            "canRetry": job["status"] == "failed" and bool(job.get("source")), "sourceReady": bool(job.get("source"))}

    def start(self, payload):
        language = payload.get("language", "auto")
        if language not in ("auto", "en", "sk", "cs", "de", "es", "fr", "pl", "it", "pt"):
            raise ValidationError("Choose a supported source language.")
        media_id, project_id, segments = payload.get("mediaId"), payload.get("projectId"), payload.get("segments")
        if payload.get("subtitleText"):
            segments = import_subtitles(payload["subtitleText"])
        if sum(bool(v) for v in (media_id, project_id, segments)) != 1:
            raise ValidationError("Choose one source recording or subtitle script.")
        job = {"id": uid(), "name": str(payload.get("name", "New Slovak draft")).strip()[:160] or "New Slovak draft",
            "language": language, "createdAt": now(), "status": "queued", "stage": "Waiting to prepare draft", "progress": 0,
            "sourceMediaId": media_id, "source": None, "translated": {}, "resultProjectId": None, "error": None}
        if media_id:
            if self.store.media(media_id).get("purpose") != "reference":
                raise ValidationError("Upload the guide's recording as source audio.")
            if not self.settings.key("elevenlabs"):
                raise ValidationError("Add your ElevenLabs API key in Services first.")
        elif project_id:
            project = self.store.get(project_id)
            if payload.get("revision") != project["revision"]:
                raise ConflictError("Save your script before translating a copy.")
            segments = project["segments"]
            job.update(style=project["style"], cueOffsetMs=project["cueOffsetMs"], musicId=project.get("musicId"))
        if language != "sk" and not self.settings.key("deepl"):
            raise ValidationError("Add your DeepL API key in Services first, or choose Slovak for an already Slovak source.")
        if not media_id:
            job["source"] = normalize_segments(segments)
            if not job["source"] or not any(s["text"].strip() for s in job["source"]):
                raise ValidationError("The source script has no text to translate.")
        with self.lock:
            if sum(j["status"] in ("queued", "working") for j in self.jobs(False)) >= 5:
                raise ValidationError("Five drafts are already queued. Let one finish first.")
            self.put(job)
            self.executor.submit(self.run, copy.deepcopy(job))
        return self.public(job)

    def retry(self, job_id):
        with self.lock:
            job = next((j for j in self.jobs(False) if j["id"] == job_id), None)
            if not job or job["status"] != "failed" or not job.get("source"):
                raise ValidationError("Only a failed draft with a saved transcript can resume.")
            if job["language"] not in ("sk", "slk") and not self.settings.key("deepl"):
                raise ValidationError("Add your DeepL API key in Services first.")
            job.update(status="queued", stage="Resuming saved draft", error=None)
            self.put(job)
            self.executor.submit(self.run, copy.deepcopy(job))
            return self.public(job)

    def run(self, job):
        def report(progress, stage):
            job.update(status="working", progress=round(progress, 1), stage=stage)
            self.put(job)
        try:
            if not job.get("source"):
                media = self.store.media(job["sourceMediaId"])
                raw = transcribe(self.store.directory / "media" / media["storedName"], self.settings.key("elevenlabs"), job["language"], report)
                # Preserve the full response, including word timing, before translation.
                (self.store.directory / "transcripts" / (job["id"] + ".json")).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
                job["source"] = scribe_cues(raw)
                job["language"] = str(raw.get("language_code") or job["language"])
                report(45, "Transcript saved locally")
            source = job["source"]
            if job["language"] in ("sk", "slk"):
                translated = copy.deepcopy(source)
            else:
                pending = [i for i, s in enumerate(source) if s["text"].strip() and str(i) not in job["translated"]]
                context = "\n".join(s["text"] for s in source)[:6000]
                # At most 40 texts and ~60KB per request, below provider limits.
                while pending:
                    batch, byte_count = [], 0
                    while pending and len(batch) < 40:
                        index = pending[0]
                        length = len(json.dumps(source[index]["text"], ensure_ascii=False).encode())
                        if batch and byte_count + length > 60000:
                            break
                        batch.append(pending.pop(0))
                        byte_count += length
                    report(45 + len(job["translated"]) / len(source) * 50, "Translating Slovak draft with DeepL")
                    texts = translate_batch([source[i]["text"] for i in batch], self.settings.key("deepl"), context)
                    job["translated"].update({str(i): text for i, text in zip(batch, texts)})
                    self.put(job)  # Resume completed batches without retranscribing or rebilling them.
                translated = [{**cue, "text": job["translated"].get(str(i), cue["text"])} for i, cue in enumerate(source)]
            reference = {"name": "Original · " + job["name"], "language": job["language"], "segments": source, "mediaId": job.get("sourceMediaId")}
            # Create only after every batch succeeds; existing sessions are never modified.
            project = self.store.create(job["name"] + " · SK draft", [{**s, "id": uid()} for s in translated], reference=reference)
            if job.get("style"):
                project.update(style=job["style"], cueOffsetMs=job["cueOffsetMs"], musicId=job.get("musicId"))
                project = self.store.save(project["id"], project)
            job.update(status="complete", stage="Ready for your Slovak review", progress=100, resultProjectId=project["id"], completedAt=now(), error=None)
        except (ValidationError, subprocess.TimeoutExpired) as error:
            message = "Preparing the recording took too long. Try a shorter source file." if isinstance(error, subprocess.TimeoutExpired) else str(error)
            job.update(status="failed", stage="Draft needs attention", error=message)
        except Exception:
            job.update(status="failed", stage="Draft needs attention", error="The draft could not be completed. Saved source text and completed translation batches are retained.")
        self.put(job)
