import copy
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from studio import Store, ConflictError, ValidationError, render_signature
from narration import Narration
from workspace import Waveforms, storage_report


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name)
        self.project = self.store.create('Private test', [
            {'id': 'one', 'startMs': 0, 'endMs': 1000, 'text': 'Nádych.'},
            {'id': 'two', 'startMs': 2000, 'endMs': 3000, 'text': 'Výdych.'}])

    def tearDown(self):
        self.temporary.cleanup()

    def test_review_changes_and_ready_handoff_follow_exact_script(self):
        p = self.project
        with self.assertRaises(ValidationError):
            self.store.save(p['id'], p, 'editor', ready=True)
        p = self.store.save(p['id'], {**p, 'reviewed': ['one', 'two']}, 'editor')
        p = self.store.save(p['id'], p, 'editor', 'Script ready', ready=True)
        self.assertTrue(p['scriptReady'])
        self.assertEqual(p['readyRevision'], p['revision'])
        signature = p['renderSignature']
        p = self.store.save(p['id'], {**p, 'favorite': True, 'archived': True}, 'owner')
        self.assertTrue(p['scriptReady'])
        self.assertEqual(signature, p['renderSignature'])
        changed = copy.deepcopy(p); changed['segments'][0]['text'] = 'Nový nádych.'
        p = self.store.save(p['id'], changed, 'editor')
        self.assertFalse(p['scriptReady'])
        self.assertEqual(p['reviewed'], ['two'])
        # A client cannot smuggle a ready approval into an ordinary save.
        forged = {**p, 'readySignature': 'forged', 'readyRevision': 999}
        p = self.store.save(p['id'], forged, 'editor')
        self.assertNotEqual(p['readySignature'], 'forged')
        p = self.store.save(p['id'], {**p, 'reviewed': ['one', 'two']}, 'editor')
        p = self.store.save(p['id'], p, 'editor', ready=True)
        p = self.store.save(p['id'], {**p, 'reviewed': ['one']}, 'editor')
        self.assertFalse(p['scriptReady'])
        self.assertFalse(self.store.summaries()[0]['scriptReady'])

    def test_timing_review_and_render_fingerprint_ignore_organization(self):
        p = self.store.save(self.project['id'], {**self.project, 'reviewed': ['one', 'two']})
        before = render_signature(p)
        changed = copy.deepcopy(p); changed['segments'][1]['startMs'] += 100
        changed = self.store.save(p['id'], changed)
        self.assertEqual(changed['reviewed'], ['one'])
        self.assertNotEqual(before, render_signature(changed))
        changed['favorite'] = True; changed['archived'] = True
        self.assertEqual(changed['renderSignature'], render_signature(changed))

    def test_version_restore_is_new_revision_and_keeps_queued_snapshot_unchanged(self):
        p = self.project
        queued = {'id': 'job', 'projectId': p['id'], 'createdAt': p['updatedAt'], 'snapshot': copy.deepcopy(p), 'status': 'queued'}
        self.store.put_job(queued)
        changed = copy.deepcopy(p); changed['segments'][0]['text'] = 'Upravené.'
        changed = self.store.save(p['id'], changed, 'Editor')
        restored = self.store.restore(p['id'], {'revision': changed['revision'], 'version': 1}, 'Owner')
        self.assertEqual(restored['revision'], 3)
        self.assertEqual(restored['segments'], p['segments'])
        versions = self.store.versions(p['id'])
        self.assertEqual([v['revision'] for v in versions], [3, 2, 1])
        self.assertEqual(versions[0]['actor'], 'Owner')
        self.assertEqual(self.store.version(p['id'], 2)['segments'][0]['text'], 'Upravené.')
        self.assertEqual(self.store.jobs()[0], queued)
        with self.assertRaises(ConflictError):
            self.store.restore(p['id'], {'revision': changed['revision'], 'version': 1}, 'Owner')
        self.assertEqual(self.store.get(p['id'])['revision'], 3)

    def test_existing_project_without_versions_is_preserved_on_first_save(self):
        with self.store.connection() as db:
            db.execute('DELETE FROM project_versions')
        changed = {**self.project, 'name': 'New name'}
        result = self.store.save(self.project['id'], changed)
        self.assertEqual(self.store.version(result['id'], 1)['name'], 'Private test')
        self.assertEqual(Store(self.temporary.name).version(result['id'], 2)['name'], 'New name')

    def test_recovery_creates_separate_session_and_never_overwrites_current_text(self):
        draft = copy.deepcopy(self.project); draft['segments'][0]['text'] = 'Recovered words'
        current = self.store.save(self.project['id'], {**self.project, 'name': 'Current NAS session'})
        recovered = self.store.recover(current['id'], draft, 'Editor')
        self.assertNotEqual(recovered['id'], current['id'])
        self.assertEqual(recovered['segments'][0]['text'], 'Recovered words')
        self.assertEqual(self.store.get(current['id']), current)
        self.assertEqual(recovered['reviewed'], [])
        self.assertFalse(recovered['scriptReady'])

    def test_storage_report_is_read_only_and_lists_retained_media(self):
        narration = Narration(self.store)
        try:
            path = self.store.directory / 'media' / 'example.wav'; path.write_bytes(b'private-synthetic-fixture')
            self.store.put_media({'id': 'example', 'name': 'Example take', 'storedName': path.name, 'bytes': path.stat().st_size, 'purpose': 'narration'})
            report = storage_report(self.store)
            self.assertEqual(report['assets'][0]['name'], 'Example take')
            self.assertEqual(report['assets'][0]['usedBy'], [])
            self.assertEqual(next(g for g in report['groups'] if g['name'] == 'media')['files'], 1)
            self.assertGreater(report['freeBytes'], 0)
            self.assertEqual(path.read_bytes(), b'private-synthetic-fixture')
            self.assertNotIn(self.temporary.name, json.dumps(report))
        finally:
            narration.executor.shutdown()

    def test_waveform_uses_bounded_scalar_output_and_is_cached_across_restart(self):
        path = self.store.directory / 'media' / 'tone.wav'
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
            audio.writeframes(b''.join(struct.pack('<h', 10000 if n % 32 < 16 else -10000) for n in range(8000)))
        with ThreadPoolExecutor(max_workers=1) as executor:
            service = Waveforms(self.store, executor)
            self.assertEqual(service.get('tone', path, 1000)['status'], 'building')
        result = service.get('tone', path, 1000)
        self.assertEqual(result['status'], 'ready')
        self.assertLessEqual(len(result['peaks']), 2000)
        self.assertGreater(max(result['peaks']), .2)
        with ThreadPoolExecutor(max_workers=1) as executor, patch('workspace.subprocess.Popen', side_effect=AssertionError('Cached waveform must not be regenerated')):
            self.assertEqual(Waveforms(self.store, executor).get('tone', path, 1000), result)

    def test_waveform_stops_its_child_promptly_when_server_shutdown_begins(self):
        path = self.store.directory / 'media' / 'retained.wav'; path.write_bytes(b'original-retained-data')
        stopping, started, children = threading.Event(), threading.Event(), []
        popen = subprocess.Popen
        def slow_child(*args, **kwargs):
            child = popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            children.append(child); started.set(); return child
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as executor, patch('workspace.subprocess.Popen', side_effect=slow_child):
            service = Waveforms(self.store, executor, stopping.is_set)
            service.get('cancelled', path, 1000)
            self.assertTrue(started.wait(3)); stopping.set()
        self.assertLess(time.monotonic()-start, 3)
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(service.get('cancelled', path, 1000)['status'], 'failed')
        self.assertEqual(path.read_bytes(), b'original-retained-data')

    def test_settings_validation_and_version_scope(self):
        for payload in ({'favorite': 'true'}, {'workflowMode': 'invalid'}, {'reviewed': 'all'}):
            with self.assertRaises(ValidationError):
                self.store.save(self.project['id'], {**self.project, **payload})
        other = self.store.create('Other', self.project['segments'])
        with self.assertRaises(KeyError):
            self.store.version(other['id'], 99)
