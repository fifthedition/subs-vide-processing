"""Private narration takes, non-destructive punch-ins and timeline WAV masters."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import wave

from export_queue import CHUNK_BYTES, file_hash
from studio import ConflictError, ValidationError, now, uid

RATE = 48000
MAX_TAKE_SECONDS = 2 * 3600
MAX_PCM_BYTES = 4 * 1024**3 - 128


def number(value, minimum, maximum):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValidationError("Enter a valid recording time or level.") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValidationError("Enter a valid recording time or level.")
    return result


def wav_header(rate, count):
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", count + 36, b"WAVE", b"fmt ", 16,
                       1, 1, rate, rate * 3, 3, 24, b"data", count)


def replace_range(clips, incoming):
    """Retain both sides of overlaps, including their source sample offsets."""
    result = []
    for clip in clips:
        left, right = clip["startFrame"], clip["endFrame"]
        if right <= incoming["startFrame"] or left >= incoming["endFrame"]:
            result.append(clip)
            continue
        if left < incoming["startFrame"]:
            result.append({**clip, "endFrame": incoming["startFrame"]})
        if right > incoming["endFrame"]:
            result.append({**clip, "startFrame": incoming["endFrame"],
                           "sourceFrame": clip["sourceFrame"] + incoming["endFrame"] - left})
    return sorted([*result, incoming], key=lambda clip: clip["startFrame"])


class Narration:
    def __init__(self, store):
        self.store = store
        self.directory = store.directory / "recordings"
        self.directory.mkdir(exist_ok=True)
        self.masters = store.directory / "narration-masters"
        self.masters.mkdir(exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="narration-wav")
        self.lock = threading.Lock()
        self.finalize_lock = threading.Lock()
        self.builds = {}
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS narrations(id TEXT PRIMARY KEY,guide_id TEXT UNIQUE,payload TEXT);
                CREATE TABLE IF NOT EXISTS narration_takes(id TEXT PRIMARY KEY,owner TEXT,session_id TEXT,payload TEXT);
            """)

    @staticmethod
    def _session(db, identifier):
        row = db.execute("SELECT payload FROM narrations WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Narration session not found.")
        return json.loads(row[0])

    @staticmethod
    def _put(db, session):
        session["updatedAt"] = now()
        db.execute("INSERT OR REPLACE INTO narrations VALUES(?,?,?)",
                   (session["id"], session["guideJobId"], json.dumps(session, ensure_ascii=False)))

    @staticmethod
    def _take(db, identifier, owner):
        row = db.execute("SELECT payload FROM narration_takes WHERE id=? AND owner=?", (identifier, owner)).fetchone()
        if not row:
            raise KeyError("Recording not found for this account.")
        return json.loads(row[0])

    @staticmethod
    def _put_take(db, take):
        take["updatedAt"] = now()
        db.execute("INSERT OR REPLACE INTO narration_takes VALUES(?,?,?,?)",
                   (take["id"], take["owner"], take["sessionId"], json.dumps(take)))

    @staticmethod
    def _revision(session, payload):
        if payload.get("revision") != session["revision"]:
            raise ConflictError("Narration changed in another window. Reload it before saving this take.")

    @staticmethod
    def _history(session):
        session["history"] = [*session.get("history", []), copy.deepcopy(session["clips"])][-20:]
        session["revision"] += 1
        session["timelineRevision"] += 1
        session["alignmentConfirmed"] = False

    def open(self, guide_id):
        guide = next((job for job in self.store.jobs() if job["id"] == guide_id), None)
        path = self.store.directory / "exports" / (str(guide_id) + ".mp4")
        if not guide or guide["status"] != "complete" or guide.get("kind") == "final" or not path.is_file():
            raise ValidationError("Choose a completed music-and-subtitles video for narration.")
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height", "-of", "json", str(path)], capture_output=True, timeout=30)
        try:
            stream = json.loads(probe.stdout)["streams"][0]
            if probe.returncode or (stream["width"], stream["height"]) != (1920, 1080):
                raise ValueError()
        except (ValueError, KeyError, IndexError):
            raise ValidationError("Render a new Full HD guide before recording narration.") from None
        duration = guide.get("result", {}).get("durationMs")
        if not duration:
            raise ValidationError("This video has no duration information. Render a new guide video.")
        snapshot = guide.get("snapshot", {})
        offset = snapshot.get("cueOffsetMs", 0)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM narrations WHERE guide_id=?", (guide_id,)).fetchone()
            if row:
                identifier = row[0]
            else:
                identifier = uid()
                session = {"id": identifier, "projectId": guide["projectId"], "guideJobId": guide_id,
                           "name": guide["projectName"], "guideRevision": guide["revision"], "durationMs": duration,
                           "sampleRate": RATE, "revision": 1, "timelineRevision": 1, "clips": [], "history": [],
                           "enhancedMediaId": None, "enhancedTimelineRevision": None, "voiceOffsetMs": 0,
                           "musicVolume": .25, "voiceVolume": 1., "alignmentConfirmed": False,
                           "cues": [{"startMs": c["startMs"] + offset, "endMs": c["endMs"] + offset, "text": c["text"]}
                                    for c in snapshot.get("segments", [])]}
                self._put(db, session)
        return self.get(identifier)

    def get(self, identifier):
        with self.store.connection() as db:
            session = self._session(db, identifier)
        master = self.master_state(session)
        public = {key: value for key, value in session.items() if key != "history"}
        public["canUndo"] = bool(session.get("history"))
        public["master"] = master
        public["enhanced"] = self.store.media(session["enhancedMediaId"]) if session.get("enhancedMediaId") else None
        public["enhancedIsCurrent"] = bool(session.get("enhancedMediaId") and
                                            session.get("enhancedTimelineRevision") == session["timelineRevision"])
        return public

    def pending(self, owner, session_id=None):
        with self.store.connection() as db:
            takes = [json.loads(row[0]) for row in db.execute("SELECT payload FROM narration_takes WHERE owner=?", (owner,))]
        return [self.take(t["id"], owner) for t in takes if t["status"] in ("recording", "finishing") and
                (session_id is None or t["sessionId"] == session_id)]

    def list(self, project_id):
        with self.store.connection() as db:
            sessions = [json.loads(row[0]) for row in db.execute("SELECT payload FROM narrations")]
        return [{"id": s["id"], "guideJobId": s["guideJobId"], "timelineRevision": s["timelineRevision"],
            "hasVoice": bool(s["clips"]), "masterReady": self.master_state(s)["status"] == "ready",
            "enhancedIsCurrent": bool(s.get("enhancedMediaId") and s.get("enhancedTimelineRevision") == s["timelineRevision"]),
            "alignmentConfirmed": s["alignmentConfirmed"]} for s in sessions if s["projectId"] == project_id]

    def take(self, identifier, owner):
        with self.store.connection() as db:
            take = self._take(db, identifier, owner)
        path = self.directory / identifier
        return {**{key: value for key, value in take.items() if key != "owner"},
                "offset": max(0, path.stat().st_size - 44) if path.is_file() else take.get("bytes", 0)}

    def start(self, identifier, owner, payload):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, identifier)
            self._revision(session, payload)
            active = [json.loads(row[0]) for row in db.execute("SELECT payload FROM narration_takes WHERE session_id=?", (identifier,))]
            if any(take["status"] in ("recording", "finishing") for take in active):
                raise ConflictError("Finish or recover the existing recording before starting another take.")
            start = round(number(payload.get("startMs"), 0, session["durationMs"] - 1))
            end = round(number(payload.get("endMs"), start + 1, session["durationMs"]))
            rate = int(number(payload.get("sampleRate"), 8000, 192000))
            take = {"id": uid(), "sessionId": identifier, "owner": owner, "status": "recording", "startMs": start,
                    "endMs": end, "sampleRate": rate, "bytes": 0, "baseRevision": session["revision"], "createdAt": now()}
            if shutil.disk_usage(self.directory).free < 128 * 1024**2:
                raise ValidationError("The NAS needs more free space for narration.")
            (self.directory / take["id"]).write_bytes(wav_header(rate, 0))
            self._put_take(db, take)
        return self.take(take["id"], owner)

    def chunk(self, identifier, owner, offset, data):
        if not 0 < len(data) <= CHUNK_BYTES or len(data) % 3:
            raise ValidationError("Upload aligned 24-bit mono PCM chunks of at most 4 MB.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            take = self._take(db, identifier, owner)
            path = self.directory / identifier
            if take["status"] != "recording" or not path.is_file():
                raise ConflictError("This recording is already finished.")
            size = path.stat().st_size - 44
            limit = min(MAX_PCM_BYTES, take["sampleRate"] * 3 * MAX_TAKE_SECONDS)
            if offset < 0 or offset > size or offset % 3 or offset + len(data) > limit:
                raise ConflictError("Resume at the recording's current upload offset.")
            if shutil.disk_usage(self.directory).free < len(data) + 64 * 1024**2:
                raise ValidationError("The NAS needs more free space for narration.")
            with path.open("r+b") as handle:
                handle.seek(44 + offset)
                if offset < size:
                    if handle.read(len(data)) != data:
                        raise ConflictError("This recording chunk differs from the saved audio.")
                else:
                    handle.write(data)
            take["bytes"] = max(size, offset + len(data))
            self._put_take(db, take)
        return {"offset": take["bytes"]}

    def finish(self, identifier, owner, payload):
        with self.finalize_lock:
            return self._finish(identifier, owner, payload)

    def _finish(self, identifier, owner, payload):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            take = self._take(db, identifier, owner)
            if take["status"] == "complete":
                return self.get(take["sessionId"])
            if take["status"] not in ("recording", "finishing"):
                raise ConflictError("This recording is already finished.")
            session = self._session(db, take["sessionId"])
            self._revision(session, payload)
            path = self.directory / identifier
            count = path.stat().st_size - 44
            if count != payload.get("bytes") or count <= 0 or count % 3:
                raise ConflictError("Upload all recorded audio before finishing the take.")
            take["status"] = "finishing"
            self._put_take(db, take)
        start = round(number(payload.get("startMs", take["startMs"]), max(0, take["startMs"] - 500),
                             min(session["durationMs"] - 1, take["startMs"] + 500)))
        with path.open("r+b") as handle:
            handle.write(wav_header(take["sampleRate"], count))
        destination = self.store.directory / "media" / (identifier + ".wav")
        # Normalize only the sample rate, never the volume. Chrome/Safari/Firefox
        # can choose a device rate other than the requested 48 kHz.
        if not destination.is_file():
            if shutil.disk_usage(destination.parent).free < count + 64 * 1024**2:
                raise ValidationError("The NAS needs more free space for narration.")
            temporary = destination.with_suffix(".tmp.wav")
            if take["sampleRate"] == RATE:
                shutil.copyfile(path, temporary)
            else:
                # Write a classic PCM WAV header ourselves. FFmpeg otherwise
                # uses WAVE_FORMAT_EXTENSIBLE for 24-bit output, which older
                # Python wave readers cannot open.
                with temporary.open("wb") as output:
                    output.write(wav_header(RATE, 0)); output.flush()
                    process = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path),
                        "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s24le", "-f", "s24le", "pipe:1"],
                        stdout=output, stderr=subprocess.PIPE, timeout=600)
                with temporary.open("r+b") as output:
                    output.write(wav_header(RATE, temporary.stat().st_size - 44))
                if process.returncode:
                    temporary.unlink(missing_ok=True)
                    raise ValidationError("The recorded WAV could not be prepared. Your original take is retained.")
            temporary.replace(destination)
        with wave.open(str(destination), "rb") as audio:
            frames = audio.getnframes()
        first = round(start * RATE / 1000)
        last = min(first + frames, round(min(take["endMs"], session["durationMs"]) * RATE / 1000))
        if last <= first:
            raise ValidationError("Record at least a short spoken section before saving.")
        media = {"id": identifier, "storedName": destination.name, "name": "Narration take " + identifier[:8] + ".wav",
                 "purpose": "narration", "durationMs": round(frames * 1000 / RATE), "sampleRate": RATE,
                 "channels": 1, "codec": "pcm_s24le", "mime": "audio/wav",
                 "bytes": destination.stat().st_size, "sha256": file_hash(destination)}
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, take["sessionId"])
            self._revision(session, payload)
            current = self._take(db, identifier, owner)
            if current["status"] == "complete":
                return self.get(current["sessionId"])
            if current["bytes"] != count:
                raise ConflictError("Recording changed while saving. Stop capture and try again.")
            db.execute("INSERT OR REPLACE INTO media VALUES(?,?)", (identifier, json.dumps(media)))
            self._history(session)
            session["clips"] = replace_range(session["clips"],
                {"mediaId": identifier, "startFrame": first, "endFrame": last, "sourceFrame": 0})
            session["lastPositionMs"] = round(last * 1000 / RATE)
            session["lastTakeId"] = identifier
            self._put(db, session)
            take.update(status="complete", bytes=count, placedStartMs=start)
            self._put_take(db, take)
        path.unlink(missing_ok=True)
        return self.get(session["id"])

    def discard(self, identifier, owner):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            take = self._take(db, identifier, owner)
            if take["status"] in ("recording", "finishing"):
                take["status"] = "discarded"
                self._put_take(db, take)
        # Raw audio is retained privately, including discarded interrupted takes.
        return {"ok": True}

    def undo(self, identifier, payload):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, identifier)
            self._revision(session, payload)
            if not session.get("history"):
                raise ValidationError("There is no narration edit to undo.")
            session["clips"] = session["history"].pop()
            session["revision"] += 1
            session["timelineRevision"] += 1
            session["alignmentConfirmed"] = False
            self._put(db, session)
        return self.get(identifier)

    def save_mix(self, identifier, payload):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, identifier)
            self._revision(session, payload)
            if payload.get("timelineRevision") != session["timelineRevision"]:
                raise ConflictError("Narration changed. Download a new WAV master before attaching enhanced audio.")
            media_id = payload.get("enhancedMediaId", session.get("enhancedMediaId"))
            if media_id:
                media = self.store.media(media_id)
                if media.get("purpose") != "enhanced":
                    raise ValidationError("Upload the Adobe-enhanced narration as enhanced audio.")
                if not session["clips"]:
                    raise ValidationError("Record and save narration before attaching enhanced audio.")
            attaching = payload.get("attachEnhanced") is True
            if media_id != session.get("enhancedMediaId") and not attaching:
                raise ValidationError("Confirm the WAV version when attaching enhanced narration.")
            if attaching and payload.get("enhancedTimelineRevision") != session["timelineRevision"]:
                raise ConflictError("Narration changed. Download a new WAV master before attaching enhanced audio.")
            basis = session["timelineRevision"] if attaching and media_id else session.get("enhancedTimelineRevision")
            confirmed = payload.get("alignmentConfirmed") is True
            if confirmed and (not media_id or basis != session["timelineRevision"]):
                raise ValidationError("Attach current enhanced narration before confirming its timing.")
            session.update(enhancedMediaId=media_id,
                enhancedTimelineRevision=basis,
                voiceOffsetMs=round(number(payload.get("voiceOffsetMs", 0), -session["durationMs"], session["durationMs"])),
                musicVolume=number(payload.get("musicVolume", .25), 0, 1),
                voiceVolume=number(payload.get("voiceVolume", 1), .01, 1),
                alignmentConfirmed=confirmed)
            session["revision"] += 1
            self._put(db, session)
        return self.get(identifier)

    def master_path(self, session):
        return self.masters / (session["id"] + "-r" + str(session["timelineRevision"]) + ".wav")

    def master_state(self, session):
        path = self.master_path(session)
        key = path.name
        with self.lock:
            state = dict(self.builds.get(key, {}))
        return {"status": "ready" if path.is_file() else state.get("status", "missing"),
                "error": state.get("error"), "timelineRevision": session["timelineRevision"]}

    def prepare_master(self, identifier, payload):
        with self.store.connection() as db:
            session = self._session(db, identifier)
            self._revision(session, payload)
        if not session["clips"]:
            raise ValidationError("Record and save narration before preparing the WAV master.")
        path = self.master_path(session)
        with self.lock:
            if not path.is_file() and self.builds.get(path.name, {}).get("status") != "building":
                self.builds[path.name] = {"status": "building"}
                self.executor.submit(self._master, copy.deepcopy(session), path)
        return self.get(identifier)

    def _master(self, session, path):
        temporary = path.with_suffix(".tmp")
        try:
            frames = round(session["durationMs"] * RATE / 1000)
            if frames * 3 > MAX_PCM_BYTES:
                raise ValidationError("This WAV is too long. Use a guide shorter than eight hours.")
            if shutil.disk_usage(path.parent).free < frames * 3 + 64 * 1024**2:
                raise ValidationError("The NAS needs more free space for narration.")
            with wave.open(str(temporary), "wb") as output:
                output.setnchannels(1); output.setsampwidth(3); output.setframerate(RATE)
                position = 0
                def silence(count):
                    while count:
                        step = min(count, RATE)
                        output.writeframesraw(b"\0" * (step * 3))
                        count -= step
                for clip in session["clips"]:
                    silence(clip["startFrame"] - position)
                    media = self.store.media(clip["mediaId"])
                    with wave.open(str(self.store.directory / "media" / media["storedName"]), "rb") as source:
                        source.setpos(clip["sourceFrame"])
                        remaining = clip["endFrame"] - clip["startFrame"]
                        while remaining:
                            step = min(remaining, RATE)
                            data = source.readframes(step)
                            if len(data) != step * 3:
                                raise ValidationError("A saved narration take is incomplete.")
                            output.writeframesraw(data); remaining -= step
                    position = clip["endFrame"]
                silence(frames - position)
            temporary.replace(path)
            state = {"status": "ready"}
        except Exception as error:
            temporary.unlink(missing_ok=True)
            state = {"status": "failed", "error": str(error)}
        with self.lock:
            self.builds[path.name] = state

