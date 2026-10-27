"""Private, bounded waveform previews and owner storage information."""
import json
import math
import re
import shutil
import subprocess
import threading
import time


class Waveforms:
    def __init__(self, store, executor, stopping=lambda: False):
        self.store, self.executor = store, executor
        self.stopping = stopping
        self.directory = store.directory / "waveforms"
        self.directory.mkdir(exist_ok=True)
        self.states, self.lock = {}, threading.Lock()

    def get(self, key, path, duration_ms):
        if not path.is_file():
            raise KeyError("Audio preview not found.")
        target = self.directory / (key + ".json")
        if target.is_file():
            return json.loads(target.read_text())
        with self.lock:
            if key not in self.states:
                if sum(s["status"] == "building" for s in self.states.values()) >= 8:
                    return {"status": "building"}
                self.states[key] = {"status": "building"}
                self.executor.submit(self._build, key, path, duration_ms, target)
            return dict(self.states[key])

    def _build(self, key, path, duration_ms, target):
        try:
            duration = max(.01, min(12 * 3600, float(duration_ms) / 1000))
            block = max(1, math.ceil(duration * 8000 / 1600))
            # Only one scalar per block is emitted; full PCM is never held in RAM.
            filters = ("aformat=channel_layouts=mono,aresample=8000,"
                f"asetnsamples=n={block}:p=0,astats=metadata=1:reset=1,"
                "ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-")
            process = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-af", filters,
                "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 180
            while True:
                if self.stopping() or time.monotonic() >= deadline:
                    process.kill(); process.communicate()
                    raise ValueError()
                try:
                    output, _ = process.communicate(timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise ValueError()
            values = re.findall(rb"Peak_level=(-?inf|[-+\d.eE]+)", output)
            peaks = [0 if value == b"-inf" else round(min(1, 10 ** (float(value) / 20)), 4) for value in values[:2000]]
            if not peaks:
                raise ValueError()
            result = {"status": "ready", "durationMs": duration_ms, "peaks": peaks}
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(result)); temporary.replace(target)
        except Exception:
            result = {"status": "failed", "error": "Waveform unavailable. Playback and numeric range controls still work."}
        with self.lock:
            self.states[key] = result


def storage_report(store):
    usage = shutil.disk_usage(store.directory)
    groups = []
    for name in ("media", "exports", "recordings", "narration-masters", "waveforms", "uploads", "render-uploads"):
        folder, size, count = store.directory / name, 0, 0
        if folder.is_dir():
            for path in folder.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    size += path.stat().st_size; count += 1
        groups.append({"name": name, "bytes": size, "files": count})
    with store.connection() as db:
        assets = [json.loads(row[0]) for row in db.execute("SELECT payload FROM media")]
        projects = [json.loads(row[0]) for row in db.execute("SELECT payload FROM projects")]
        narrations = [json.loads(row[0]) for row in db.execute("SELECT payload FROM narrations")]
        history_bytes = db.execute("SELECT COALESCE(SUM(LENGTH(CAST(payload AS BLOB))),0) FROM project_versions").fetchone()[0]
    names = {p["id"]: p["name"] for p in projects}
    used = {}
    def remember(identifier, project):
        if identifier:
            used.setdefault(identifier, set()).add(names.get(project, "Retained session"))
    for p in projects:
        remember(p.get("musicId"), p["id"]); remember(p.get("reference", {}).get("mediaId"), p["id"])
    for n in narrations:
        for clip in [*n.get("clips", []), *(c for edit in n.get("history", []) for c in edit)]:
            remember(clip.get("mediaId"), n["projectId"])
        remember(n.get("enhancedMediaId"), n["projectId"])
    for job in store.jobs():
        remember(job.get("music", {}).get("id"), job["projectId"])
        remember(job.get("voice", {}).get("id"), job["projectId"])
    return {"freeBytes": usage.free, "totalBytes": usage.total, "groups": groups, "historyBytes": history_bytes,
        "assets": sorted([{"id": a["id"], "name": a["name"], "purpose": a.get("purpose", "music"),
            "bytes": a.get("bytes", 0), "usedBy": sorted(used.get(a["id"], []))} for a in assets], key=lambda a: a["bytes"], reverse=True)}
