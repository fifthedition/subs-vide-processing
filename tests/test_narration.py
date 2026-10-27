import copy
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import unittest
import wave

from export_queue import ExportQueue, RENDERER_VERSION, PROTOCOL
from narration import Narration, RATE
from studio import Store, ValidationError, ConflictError, normalize_project, render_video
from test_studio import synthetic_audio


class NarrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        root = Path(cls.fixture.name)
        synthetic_audio(root / "music.wav", 3)
        cls.project = normalize_project({"name": "Narration example", "revision": 5, "cueOffsetMs": 0,
            "segments": [{"id": "one", "startMs": 0, "endMs": 2500, "text": "Nadýchni sa. Ľahko a pokojne."}],
            "style": {"layout": "single"}})
        render_video(cls.project, root / "music.wav", root / "guide.mp4")
        cls.video = (root / "guide.mp4").read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.service = Narration(self.store)
        self.project = self.store.create(self.project["name"], self.project["segments"])
        self.guide_id = "a" * 32
        (self.root / "exports" / (self.guide_id + ".mp4")).write_bytes(self.video)
        self.store.put_job({"id": self.guide_id, "projectId": self.project["id"], "projectName": self.project["name"],
            "revision": self.project["revision"], "status": "complete", "kind": "guide", "createdAt": "2026-10-27T12:00:00Z",
            "snapshot": {**self.project, "revision": self.project["revision"]}, "result": {"durationMs": 3000}})
        self.session = self.service.open(self.guide_id)

    def tearDown(self):
        self.service.executor.shutdown(wait=True)
        self.temp.cleanup()

    def record(self, start, end, value=1000000):
        take = self.service.start(self.session["id"], "editor", {"revision": self.session["revision"],
                    "startMs": start, "endMs": end, "sampleRate": RATE})
        sample = int(value).to_bytes(3, "little", signed=True)
        raw = sample * round((end-start)*RATE/1000)
        self.service.chunk(take["id"], "editor", 0, raw)
        self.session = self.service.finish(take["id"], "editor",
            {"revision": self.session["revision"], "bytes": len(raw)})
        return take

    def enhanced(self):
        path = self.root / "media/enhanced.wav"
        synthetic_audio(path, 3)
        self.store.put_media({"id": "enhanced", "name": "Enhanced.wav", "purpose": "enhanced", "storedName": path.name,
            "durationMs": 3000, "bytes": path.stat().st_size, "channels": 1, "sampleRate": 16000})
        return {"revision": self.session["revision"], "timelineRevision": self.session["timelineRevision"],
                "attachEnhanced": True, "enhancedTimelineRevision": self.session["timelineRevision"],
                "enhancedMediaId": "enhanced", "voiceOffsetMs": 0, "musicVolume": .25, "voiceVolume": 1,
                "alignmentConfirmed": True}

    def test_resumable_chunks_account_scope_and_idempotent_finish(self):
        take = self.service.start(self.session["id"], "editor", {"revision": 1, "startMs": 0, "endMs": 1000, "sampleRate": RATE})
        data = b"\1\0\0" * RATE
        self.service.chunk(take["id"], "editor", 0, data[:999])
        self.assertEqual(self.service.chunk(take["id"], "editor", 0, data[:999])["offset"], 999)
        with self.assertRaises(ConflictError):
            self.service.chunk(take["id"], "editor", 0, b"\0" * 999)
        with self.assertRaises(KeyError):
            self.service.chunk(take["id"], "another-editor", 999, data[999:])
        with self.assertRaises(ConflictError):
            self.service.finish(take["id"], "editor", {"revision": 1, "bytes": len(data)})
        self.service.chunk(take["id"], "editor", 999, data[999:])
        self.session = self.service.finish(take["id"], "editor", {"revision": 1, "bytes": len(data)})
        again = self.service.finish(take["id"], "editor", {"revision": 1, "bytes": len(data)})
        self.assertEqual(again["revision"], self.session["revision"])
        self.assertEqual(again["clips"], self.session["clips"])
        self.assertEqual(self.service.pending("editor"), [])
        restarted = Narration(self.store)
        try:
            self.assertEqual(restarted.get(self.session["id"])["clips"], self.session["clips"])
        finally:
            restarted.executor.shutdown(wait=True)

    def test_punch_in_keeps_original_offsets_silence_duration_and_undo(self):
        original = self.record(0, 2000, 1000000)
        self.record(500, 1000, 2000000)
        clips = self.session["clips"]
        self.assertEqual([(c["startFrame"],c["endFrame"],c["sourceFrame"]) for c in clips],
                         [(0,24000,0),(24000,48000,0),(48000,96000,48000)])
        self.service.prepare_master(self.session["id"], {"revision": self.session["revision"]})
        self.service.executor.shutdown(wait=True)
        with wave.open(str(self.service.master_path(self.session)), "rb") as source:
            self.assertEqual((source.getnchannels(),source.getsampwidth(),source.getframerate(),source.getnframes()), (1,3,48000,144000))
            for frame,value in ((12000,1000000),(36000,2000000),(60000,1000000),(120000,0)):
                source.setpos(frame)
                self.assertEqual(int.from_bytes(source.readframes(1),"little",signed=True),value)
        self.session = self.service.undo(self.session["id"], {"revision": self.session["revision"]})
        self.assertEqual(len(self.session["clips"]),1)
        self.assertEqual(self.session["clips"][0]["mediaId"],original["id"])
        self.assertEqual(self.session["master"]["status"],"missing")

    def test_take_recovery_conflicts_never_drop_saved_audio(self):
        take = self.service.start(self.session["id"], "editor", {"revision": 1, "startMs": 0, "endMs": 1000, "sampleRate": RATE})
        data = b"\1\0\0" * RATE
        self.service.chunk(take["id"], "editor", 0, data)
        self.session = self.service.save_mix(self.session["id"], {"revision": 1, "timelineRevision": 1})
        with self.assertRaises(ConflictError):
            self.service.finish(take["id"], "editor", {"revision": 1, "bytes": len(data)})
        self.assertEqual(self.service.pending("editor")[0]["offset"],len(data))
        self.session = self.service.finish(take["id"], "editor", {"revision": self.session["revision"], "bytes": len(data)})
        self.assertEqual(self.session["clips"][0]["endFrame"],RATE)

    def test_enhanced_audio_goes_stale_after_retakes_and_mix_saves_do_not_revalidate_it(self):
        self.record(0,1000)
        self.session = self.service.save_mix(self.session["id"],self.enhanced())
        self.assertTrue(self.session["enhancedIsCurrent"])
        self.record(500,1000)
        self.assertFalse(self.session["enhancedIsCurrent"])
        self.session = self.service.save_mix(self.session["id"], {"revision": self.session["revision"],
            "timelineRevision": self.session["timelineRevision"], "enhancedMediaId": "enhanced", "musicVolume": .4})
        self.assertFalse(self.session["enhancedIsCurrent"])
        with self.assertRaises(ValidationError):
            ExportQueue(self.store).enqueue_final(self.session,self.session["revision"])

    def test_final_export_freezes_source_video_voice_levels_and_subtitle_revision(self):
        self.record(0,1000)
        self.session = self.service.save_mix(self.session["id"],self.enhanced())
        queue = ExportQueue(self.store)
        job = queue.enqueue_final(self.session,self.session["revision"])
        self.assertEqual(queue.enqueue_final(self.session,self.session["revision"])["id"],job["id"])
        changed = self.service.save_mix(self.session["id"], {"revision": self.session["revision"],
            "timelineRevision": self.session["timelineRevision"], "musicVolume": .4, "voiceVolume": 1,
            "voiceOffsetMs": 0, "alignmentConfirmed": True})
        with self.assertRaises(ConflictError):
            queue.enqueue_final(changed,changed["revision"])
        self.project["segments"][0]["text"] = "Changed after rendering"
        self.store.save(self.project["id"],self.project)
        claim = queue.claim("mac",PROTOCOL,RENDERER_VERSION)
        self.assertEqual(claim["project"]["segments"][0]["text"],"Nadýchni sa. Ľahko a pokojne.")
        self.assertEqual(claim["mix"]["musicVolume"],.25)
        self.assertEqual(queue.voice(job["id"],"mac",claim["attempt"]).name,"enhanced.wav")
        with self.assertRaises(ConflictError):
            queue.voice(job["id"],"other-mac",claim["attempt"])
        self.assertEqual(self.service.open(self.guide_id)["id"],self.session["id"])
        self.assertNotIn("voice",queue.list()[0])


class MixTests(unittest.TestCase):
    def test_mix_copies_video_packets_preserves_stereo_and_offsets_voice(self):
        import array,math
        from mixing import render_mix
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            music,voice,guide,final=[root/name for name in ("music.wav","voice.wav","guide.mp4","final.mp4")]
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                "aevalsrc=0.07*sin(2*PI*440*t)|0.07*sin(2*PI*880*t):s=48000:d=3","-c:a","pcm_s24le",str(music)],check=True)
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                "sine=frequency=1600:sample_rate=48000:duration=1","-c:a","pcm_s24le",str(voice)],check=True)
            # Legacy static guides can end their video packets before the
            # music. Keep that condition deterministic on every FFmpeg version.
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                "color=c=black:s=1920x1080:r=25:d=2.5","-i",str(music),"-map","0:v:0","-map","1:a:0",
                "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                "-c:a","aac","-b:a","320k",str(guide)],check=True)
            render_mix(guide,voice,final,{"musicVolume":.5,"voiceVolume":1,"voiceOffsetMs":1000})
            def hashes(path):
                result=json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_packets","-show_data_hash","sha256","-of","json",str(path)]))
                return [p["data_hash"] for p in result["packets"]]
            self.assertEqual(hashes(guide),hashes(final))
            def spectrum(at):
                raw=subprocess.check_output(["ffmpeg","-v","error","-ss",str(at),"-i",str(final),"-t","0.3","-f","f32le","pipe:1"])
                samples=array.array("f");samples.frombytes(raw)
                def strength(values,f):
                    return abs(sum(v*complex(math.cos(2*math.pi*f*n/48000),math.sin(2*math.pi*f*n/48000)) for n,v in enumerate(values)))
                left,right=samples[::2],samples[1::2]
                return {f:(strength(left,f),strength(right,f)) for f in (440,880,1600)}
            before,during,after=spectrum(.3),spectrum(1.3),spectrum(2.65)
            self.assertGreater(during[440][0],50*during[440][1])
            self.assertGreater(during[880][1],50*during[880][0])
            self.assertGreater(during[1600][0],100*before[1600][0])
            self.assertGreater(during[1600][1],100*after[1600][1])
            self.assertGreater(after[440][0],100)
            self.assertGreater(after[880][1],100)
            info=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(final)]))
            self.assertEqual(next(s["channels"] for s in info["streams"] if s["codec_type"]=="audio"),2)
            def timings(path):
                return json.loads(subprocess.check_output(["ffprobe","-v","error","-show_entries",
                    "format=duration:stream=codec_type,duration,start_time,nb_frames,avg_frame_rate",
                    "-of","json",str(path)]))
            self.assertAlmostEqual(float(info["format"]["duration"]),3,delta=.08,
                msg=json.dumps({"guide":timings(guide),"final":timings(final)}))

# Exercise browser-facing recording routes and both immutable worker assets.
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import test_remote as remote


class NarrationHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        NarrationTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        NarrationTests.tearDownClass.__func__(cls)

    setUp = remote.HTTPWorkerTests.setUp
    tearDown = remote.HTTPWorkerTests.tearDown
    request = remote.HTTPWorkerTests.request

    def test_editor_records_wav_then_owner_runs_final_mix_worker(self):
        project = self.app.store.create("HTTP narration", self.project["segments"])
        guide_id = "b" * 32
        (self.directory / "nas/exports" / (guide_id + ".mp4")).write_bytes(self.video)
        self.app.store.put_job({"id": guide_id, "kind": "guide", "projectId": project["id"], "projectName": project["name"],
            "revision": project["revision"], "snapshot": project, "status": "complete", "createdAt": "2026-10-27T12:00:00Z",
            "result": {"durationMs": 3000}})
        _, created = self.request("/api/admin/users", {"username": "narrator", "password": "narrator-example-password"})
        response, editor = self.request("/api/auth/login", {"username": "narrator", "password": "narrator-example-password"})
        headers = {"Cookie": response.headers["Set-Cookie"].split(";")[0], "X-CSRF-Token": editor["csrf"]}
        response, part = self.request("/api/jobs/" + guide_id + "/play", headers={**headers, "Range": "bytes=0-16"})
        self.assertEqual(part, self.video[:17])
        self.assertEqual(response.status, 206)
        self.assertNotIn("Content-Disposition", response.headers)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/jobs/" + guide_id + "/play", headers={"Cookie": ""})
        self.assertEqual(error.exception.code, 401); error.exception.close()
        _, session = self.request("/api/narration/open", {"guideJobId": guide_id}, headers)
        _, take = self.request("/api/narration/" + session["id"] + "/take",
            {"revision": session["revision"], "startMs": 500, "endMs": 2000, "sampleRate": 44100}, headers)
        raw = (100000).to_bytes(3,"little",signed=True) * 44100
        def binary(route, data, request_headers):
            request = Request(self.base + route, data=data, headers={"Content-Type": "application/octet-stream",
                **request_headers, "X-Upload-Offset": "0"}, method="POST")
            with urlopen(request,timeout=30) as response:
                return json.load(response)
        binary("/api/recordings/" + take["id"] + "/chunk", raw, headers)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/recordings/" + take["id"])  # owner cannot mutate another account's in-flight capture
        self.assertEqual(error.exception.code,404);error.exception.close()
        _, session = self.request("/api/recordings/" + take["id"] + "/finish",
            {"revision": session["revision"], "bytes": len(raw)}, headers)
        self.assertEqual(session["clips"][0]["startFrame"],24000)
        self.assertEqual(session["clips"][0]["endFrame"],72000)
        _, session = self.request("/api/narration/" + session["id"] + "/master", {"revision": session["revision"]}, headers)
        for attempt in range(100):
            _, session = self.request("/api/narration/" + session["id"], headers=headers)
            if session["master"]["status"] == "ready":break
            time.sleep(.02)
        self.assertEqual(session["master"]["status"],"ready")
        response, master = self.request("/api/narration/" + session["id"] + "/master", headers=headers)
        response, first_bytes = self.request("/api/narration/" + session["id"] + "/master?version=" + str(session["timelineRevision"]) + "&play=1",
            headers={**headers, "Range": "bytes=0-43"})
        self.assertEqual(response.status,206)
        self.assertEqual(first_bytes,master[:44])
        self.assertNotIn("Content-Disposition",response.headers)
        import io
        with wave.open(io.BytesIO(master),"rb") as wav:
            self.assertEqual((wav.getnframes(),wav.getframerate(),wav.getsampwidth()),(144000,48000,3))
        enhanced = self.directory / "enhanced.wav"
        synthetic_audio(enhanced,3)
        data=enhanced.read_bytes()
        _, upload = self.request("/api/uploads", {"name":"Enhanced.wav","purpose":"enhanced","bytes":len(data),"key":"enhanced-fixture"})
        binary("/api/uploads/" + upload["id"] + "/chunk",data,{"Cookie":self.cookie,"X-CSRF-Token":self.csrf})
        _, media = self.request("/api/uploads/" + upload["id"] + "/finish",{})
        body={"revision":session["revision"],"timelineRevision":session["timelineRevision"],
              "enhancedMediaId":media["id"],"attachEnhanced":True,"enhancedTimelineRevision":session["timelineRevision"],
              "voiceOffsetMs":250,"musicVolume":.25,"voiceVolume":1,"alignmentConfirmed":False}
        _, session = self.request("/api/narration/" + session["id"] + "/mix",body)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/narration/" + session["id"] + "/render",{"revision":session["revision"]})
        self.assertEqual(error.exception.code,400);error.exception.close()
        body.update(revision=session["revision"],alignmentConfirmed=True)
        _, session = self.request("/api/narration/" + session["id"] + "/mix",body)
        _, final = self.request("/api/narration/" + session["id"] + "/render",{"revision":session["revision"]})
        self.assertEqual(final["kind"],"final")
        _, worker=self.request("/api/admin/workers",{"name":"Narration test worker"})
        token=self.directory/"worker-token";token.write_text(worker["token"]);os.chmod(token,0o600)
        process=subprocess.run([sys.executable,"worker.py","--url",self.base,"--token-file",str(token),
            "--cache",str(self.directory/"mac"),"--allow-local-test"],cwd=Path(__file__).resolve().parents[1],
            capture_output=True,text=True,timeout=45)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        self.assertIn("Queue empty. 1 video(s) uploaded; 0 failed.",process.stdout)
        response,result=self.request("/api/jobs/"+final["id"]+"/download",headers=headers)
        self.assertIn("_final_r",response.headers["Content-Disposition"])
        self.assertGreater(len(result),10000)
        _, jobs=self.request("/api/jobs")
        completed=next(job for job in jobs if job["id"]==final["id"])
        self.assertEqual(completed["status"],"complete")
        for key in ("snapshot","voice","mix","music","attempt","workerId"):
            self.assertNotIn(key,completed)


