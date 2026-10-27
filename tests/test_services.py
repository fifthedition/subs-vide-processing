import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import DraftService, ServiceSettings, request_json, scribe_cues, transcribe, translate_batch
from studio import Store, ValidationError
from test_studio import synthetic_audio


class ManualExecutor:
    def submit(self, *args):
        pass


class ServiceTests(unittest.TestCase):
    def service(self, directory):
        service = DraftService(Store(directory))
        service.executor.shutdown()
        service.executor = ManualExecutor()
        service.settings.save({"elevenlabs": "test-eleven-secret", "deepl": "test-deepl-secret:fx"})
        return service

    @patch.dict(os.environ, {"ELEVENLABS_API_KEY": "", "DEEPL_AUTH_KEY": ""})
    def test_keys_are_private_not_returned_and_blank_keeps_saved_key(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = ServiceSettings(directory)
            public = settings.save({"elevenlabs": "private-example", "deepl": "example:fx"})
            self.assertNotIn("private-example", json.dumps(public))
            self.assertTrue(public["elevenlabs"]["configured"])
            self.assertEqual(stat.S_IMODE(settings.path.stat().st_mode), 0o600)
            settings.save({"elevenlabs": ""})
            self.assertEqual(settings.key("elevenlabs"), "private-example")
            settings.save({"remove_elevenlabs": True})
            self.assertFalse(settings.public()["elevenlabs"]["configured"])
            with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "env-example"}):
                self.assertTrue(settings.public()["elevenlabs"]["fromEnvironment"])
                self.assertEqual(settings.key("elevenlabs"), "env-example")

    def test_word_timestamps_make_phrases_without_filling_silence(self):
        result = {"words": [
            {"type": "word", "text": "Breathe", "start": .25, "end": .7},
            {"type": "spacing", "text": " ", "start": .7, "end": .7},
            {"type": "word", "text": "in.", "start": .75, "end": 1.2},
            {"type": "audio_event", "text": "(music)", "start": 1.2, "end": 4},
            {"type": "word", "text": "Relax.", "start": 4.25, "end": 5.1}]}
        cues = scribe_cues(result)
        self.assertEqual([(s["startMs"], s["endMs"], s["text"]) for s in cues], [(250, 1200, "Breathe in."), (4250, 5100, "Relax.")])
        with self.assertRaises(ValidationError):
            scribe_cues({"text": "Missing timing", "words": []})

    def test_provider_contract_and_incomplete_translation_is_rejected(self):
        requests = []
        def fake(request, provider, **kwargs):
            requests.append(request)
            return {"translations": [{"text": "Nadýchni sa."}, {"text": "Uvoľni sa."}]}
        with patch("services.request_json", side_effect=fake):
            result = translate_batch(["Breathe in.", "Relax."], "example:fx", "Guided meditation")
        self.assertEqual(result, ["Nadýchni sa.", "Uvoľni sa."])
        self.assertEqual(requests[0].full_url, "https://api-free.deepl.com/v2/translate")
        self.assertEqual(json.loads(requests[0].data)["target_lang"], "SK")
        with patch("services.request_json", return_value={"translations": [{"text": "Missing second cue"}]}):
            with self.assertRaisesRegex(ValidationError, "incomplete"):
                translate_batch(["one", "two"], "key", "")

    def test_streamed_transcription_form_and_credentials_do_not_enter_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            synthetic_audio(source, .2)
            def fake(request, provider, **kwargs):
                body = b"".join(request.data)
                self.assertEqual(int(request.get_header("Content-length")), len(body))
                self.assertIn(b'scribe_v2', body)
                self.assertIn(b'name="language_code"\r\n\r\nen', body)
                self.assertNotIn(b"test-secret", body)
                self.assertIn(b'name="file"; filename="source.mp3"', body)
                return {"words": []}
            with patch("services.request_json", side_effect=fake):
                transcribe(source, "test-secret", "en", lambda *args: None)

    @patch.dict(os.environ, {"ELEVENLABS_API_KEY": "", "DEEPL_AUTH_KEY": ""})
    def test_failed_translation_resumes_cached_batches_and_preserves_current_session(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            original = service.store.create("Original English", [{"id": str(i), "startMs": i * 2000, "endMs": i * 2000 + 1000, "text": "Breathe " + str(i)} for i in range(85)])
            before = service.store.get(original["id"])
            initial_count = len(service.store.summaries())
            job = service.start({"projectId": original["id"], "revision": original["revision"], "name": "Translated", "language": "en"})
            calls = []
            def fail_second(texts, *args):
                calls.append(texts)
                if len(calls) == 2:
                    raise ValidationError("DeepL quota reached")
                return ["Nádych " + text.split()[-1] for text in texts]
            with patch("services.translate_batch", side_effect=fail_second):
                service.run(service.jobs(False)[0])
            failed = service.jobs()[0]
            self.assertTrue(failed["canRetry"])
            self.assertNotIn("source", failed)
            self.assertEqual(len(service.store.summaries()), initial_count)
            self.assertEqual(service.store.get(original["id"]), before)
            service.retry(job["id"])
            with patch("services.translate_batch", side_effect=lambda texts, *args: ["Nádych " + text.split()[-1] for text in texts]) as translator:
                service.run(service.jobs(False)[0])
            self.assertEqual([len(call.args[0]) for call in translator.call_args_list], [40, 5])
            completed = service.jobs()[0]
            draft = service.store.get(completed["resultProjectId"])
            self.assertEqual(completed["status"], "complete")
            self.assertEqual(draft["reference"]["segments"], before["segments"])
            self.assertEqual([(c["startMs"], c["endMs"]) for c in draft["segments"]], [(c["startMs"], c["endMs"]) for c in before["segments"]])
            self.assertTrue(all(c["text"].startswith("Nádych") for c in draft["segments"]))
            self.assertEqual(service.store.get(original["id"]), before)

    @patch.dict(os.environ, {"ELEVENLABS_API_KEY": "", "DEEPL_AUTH_KEY": ""})
    def test_slovak_source_skips_translation_and_cannot_become_music(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            service.settings.save({"remove_deepl": True})
            media = {"id": "sourceaudio", "storedName": "source.wav", "name": "Original voice.wav", "purpose": "reference"}
            service.store.put_media(media)
            job = service.start({"mediaId": media["id"], "name": "Slovak session", "language": "sk"})
            raw = {"language_code": "slk", "words": [{"type": "word", "start": .5, "end": 1.5, "text": "Nadýchni sa."}]}
            with patch("services.transcribe", return_value=raw), patch("services.translate_batch") as translator:
                service.run(service.jobs(False)[0])
                translator.assert_not_called()
            completed = service.jobs()[0]
            draft = service.store.get(completed["resultProjectId"])
            self.assertIsNone(draft["musicId"])
            self.assertEqual(draft["reference"]["mediaId"], media["id"])
            self.assertEqual(json.loads((Path(directory) / "transcripts" / (job["id"] + ".json")).read_text()), raw)
            draft["musicId"] = media["id"]
            with self.assertRaisesRegex(ValidationError, "separate music"):
                service.store.save(draft["id"], draft)

    def test_provider_error_does_not_expose_key_or_response_body(self):
        secret = "never-show-this-key"
        error = HTTPError("https://api.deepl.com/v2/translate", 403, "Forbidden", {}, io.BytesIO(secret.encode()))
        with patch("services.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(ValidationError, "HTTP 403") as captured:
                request_json(None, "DeepL")
            self.assertNotIn(secret, str(captured.exception))


if __name__ == "__main__":
    unittest.main()
