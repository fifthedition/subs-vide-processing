"""Resumable browser audio uploads using bounded, idempotent chunks."""
import json
import mimetypes
from pathlib import Path
import shutil
import time

from export_queue import CHUNK_BYTES, file_hash
from studio import ConflictError, ValidationError, probe_audio, uid


class Uploads:
    def __init__(self, store):
        self.store = store
        self.directory = store.directory / "uploads"
        self.directory.mkdir(exist_ok=True)
        with store.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,owner TEXT,client_key TEXT,payload TEXT,updated REAL)")
        self.cleanup()

    def cleanup(self):
        with self.store.connection() as db:
            for row in db.execute("SELECT id FROM uploads WHERE updated<?", (time.time() - 7 * 86400,)).fetchall():
                (self.directory / row[0]).unlink(missing_ok=True)
                db.execute("DELETE FROM uploads WHERE id=?", (row[0],))

    def start(self, owner, payload):
        name = Path(str(payload.get("name", "music.mp3"))).name[:200]
        purpose = payload.get("purpose", "music")
        size = int(payload.get("bytes", 0))
        key = str(payload.get("key", ""))
        if purpose not in ("music", "reference", "enhanced") or not 0 < size <= 4 * 1024 ** 3 or not 1 <= len(key) <= 200:
            raise ValidationError("Choose music or source audio smaller than 4 GB.")
        extension = Path(name).suffix.lower()
        if extension not in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aif", ".aiff", ".mp4"):
            raise ValidationError("Use MP3, WAV, M4A, AAC, FLAC, OGG, or AIFF audio.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM uploads WHERE owner=? AND client_key=?", (owner, key)).fetchone()
            if row:
                item = json.loads(row["payload"])
                if any(item[k] != v for k, v in (("name", name), ("purpose", purpose), ("bytes", size))):
                    raise ConflictError("This resume key belongs to a different upload.")
            else:
                if shutil.disk_usage(self.directory).free < size + 512 * 1024 ** 2:
                    raise ValidationError("The NAS needs more free space for this audio file.")
                item = {"id": uid(), "name": name, "purpose": purpose, "bytes": size, "extension": extension}
                (self.directory / item["id"]).touch()
                db.execute("INSERT INTO uploads VALUES(?,?,?,?,?)", (item["id"], owner, key, json.dumps(item), time.time()))
            db.execute("UPDATE uploads SET updated=? WHERE id=?", (time.time(), item["id"]))
        return {"id": item["id"], "offset": (self.directory / item["id"]).stat().st_size if not item.get("media") else size,
                "chunkBytes": CHUNK_BYTES, "media": item.get("media")}

    def _get(self, db, owner, upload_id):
        row = db.execute("SELECT payload FROM uploads WHERE id=? AND owner=?", (upload_id, owner)).fetchone()
        if not row:
            raise KeyError("Upload not found. Select the file again to start an upload.")
        return json.loads(row[0])

    def chunk(self, owner, upload_id, offset, data):
        if not 0 < len(data) <= CHUNK_BYTES:
            raise ValidationError("Upload a chunk of at most 4 MB.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            item = self._get(db, owner, upload_id)
            path = self.directory / upload_id
            if item.get("media") or not path.exists() or offset < 0 or offset > path.stat().st_size or offset + len(data) > item["bytes"]:
                raise ConflictError("Resume at the upload's current offset.")
            with path.open("r+b") as handle:
                handle.seek(offset)
                if offset < path.stat().st_size:
                    if handle.read(len(data)) != data:
                        raise ConflictError("This chunk differs from the previously uploaded file.")
                else:
                    handle.write(data)
                    handle.flush()
            db.execute("UPDATE uploads SET updated=? WHERE id=?", (time.time(), upload_id))
            return {"offset": path.stat().st_size}

    def finish(self, owner, upload_id):
        # Serialize finish/retry with chunk requests and other finish requests.
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            item = self._get(db, owner, upload_id)
            if item.get("media"):
                return item["media"]
            path = self.directory / upload_id
            target = self.store.directory / "media" / (upload_id + item["extension"])
            candidate = path if path.is_file() else target
            if not candidate.is_file() or candidate.stat().st_size != item["bytes"]:
                raise ConflictError("The audio upload is not complete yet.")
            media = {"id": upload_id, "name": item["name"], "purpose": item["purpose"], "storedName": target.name,
                     "bytes": item["bytes"], "mime": mimetypes.guess_type(item["name"])[0] or "audio/mpeg",
                     "sha256": file_hash(candidate), **probe_audio(candidate)}
            if candidate != target:
                candidate.replace(target)
            db.execute("INSERT OR REPLACE INTO media VALUES(?,?)", (upload_id, json.dumps(media)))
            item["media"] = media
            db.execute("UPDATE uploads SET payload=?,updated=? WHERE id=?", (json.dumps(item), time.time(), upload_id))
        return media
