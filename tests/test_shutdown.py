"""Real process signals, request draining, stalled work and restart persistence."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen

from studio import ROOT, Store


FIXTURE = r'''
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys, time
from app import Application, Handler
from lifecycle import serve

root, scenario = Path(sys.argv[1]), sys.argv[2]
application = Application(root / 'nas', True, 'https://studio.example')
if not application.store.summaries():
    application.store.create('Kept through restart', [{'startMs':0,'endMs':1000,'text':'Synthetic shutdown fixture.'}])

class TestHandler(Handler):
    def setup(self):
        super().setup()
        (root / ('connection-' + str(self.client_address[1]))).touch()

    def get_request(self):
        if self.path == '/api/health?drain':
            (root / 'request-active').touch()
            while not (root / 'release-request').exists(): time.sleep(.01)
            application.store.create('Completed active request', [{'startMs':0,'endMs':1000,'text':'Retained.'}])
            self.send_json({'finished':True})
        else:
            super().get_request()

executors = (application.executor, application.drafts.executor, application.narration.executor)
if scenario == 'workers':
    def running(index):
        (root / ('running-' + str(index))).touch()
        while not (root / 'release-workers').exists(): time.sleep(.01)
        (root / ('finished-' + str(index))).touch()
    for index, executor in enumerate(executors):
        executor.submit(running, index)
        future = executor.submit(lambda i=index: (root / ('unexpected-' + str(i))).touch())
        future.add_done_callback(lambda result, i=index: (root / ('cancelled-' + str(i))).touch() if result.cancelled() else None)
elif scenario == 'stall':
    def stalled():
        (root / 'worker-active').touch()
        time.sleep(60)
    application.drafts.executor.submit(stalled)

server = ThreadingHTTPServer(('127.0.0.1', 0), partial(TestHandler, application=application))
(root / 'port').write_text(str(server.server_port))
serve(server, application.requests, executors, shutdown_timeout=.5 if scenario == 'stall' else 5)
'''


@unittest.skipUnless(hasattr(signal, 'SIGTERM'), 'Requires process signals')
class ShutdownTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.processes = []
        self.outputs = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        for output in self.outputs:
            output.close()
        self.temp.cleanup()

    def until(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(.01)
        self.fail('Timed out waiting for the shutdown fixture: ' + self.log())

    def log(self):
        return self.log_path.read_text() if self.log_path.exists() else ''

    def start(self, scenario='idle'):
        (self.root / 'port').unlink(missing_ok=True)
        self.log_path = self.root / ('output-' + str(len(self.processes)))
        output = self.log_path.open('w+')
        self.outputs.append(output)
        self.process = subprocess.Popen([sys.executable, '-u', '-c', FIXTURE, str(self.root), scenario],
            cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        self.processes.append(self.process)
        self.until(lambda: (self.root / 'port').is_file() and (self.root / 'port').read_text().isdigit())
        self.port = int((self.root / 'port').read_text())
        self.until(self.ready)

    def ready(self):
        try:
            return self.get('/api/health')['ready']
        except OSError:
            return False

    def get(self, path):
        request = Request(f'http://127.0.0.1:{self.port}' + path, headers={'Host':'studio.example'})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def stop(self, sig=signal.SIGTERM):
        self.process.send_signal(sig)
        self.until(lambda: 'Shutdown requested' in self.log())

    def assert_stopped(self, code=0):
        self.assertEqual(self.process.wait(timeout=5), code, self.log())
        if code == 0:
            self.assertIn('Shutdown complete.', self.log())
            self.assertNotIn('deadline reached', self.log())

    def idle_socket(self):
        connection = socket.create_connection(('127.0.0.1', self.port), timeout=3)
        self.until(lambda: (self.root / ('connection-' + str(connection.getsockname()[1]))).exists())
        return connection

    def test_term_and_int_exit_normally_and_preserve_projects(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=sig):
                self.start()
                self.stop(sig)
                self.assert_stopped()
                self.assertEqual(Store(self.root / 'nas').summaries()[0]['name'], 'Kept through restart')

    def test_idle_browser_socket_does_not_hold_shutdown_open(self):
        self.start()
        with self.idle_socket():
            self.stop()
            self.assert_stopped()

    def test_active_request_finishes_and_late_requests_receive_503(self):
        self.start()
        with self.idle_socket() as idle, ThreadPoolExecutor(max_workers=1) as client:
            response = client.submit(self.get, '/api/health?drain')
            self.until(lambda: (self.root / 'request-active').exists())
            self.stop()
            self.assertIsNone(self.process.poll())
            # The accepted socket sends its request after admission is closed.
            idle.sendall(b'GET /api/health HTTP/1.0\r\nHost: studio.example\r\n\r\n')
            self.assertIn(b'503', idle.recv(1024).split(b'\r\n',1)[0])
            (self.root / 'release-request').touch()
            self.assertTrue(response.result(timeout=3)['finished'])
            self.assert_stopped()
        self.assertIn('Completed active request', [p['name'] for p in Store(self.root / 'nas').summaries()])

    def test_all_pools_cancel_pending_jobs_before_waiting_for_running_work(self):
        self.start('workers')
        self.until(lambda: all((self.root / ('running-' + str(i))).exists() for i in range(3)))
        self.stop()
        self.until(lambda: all((self.root / ('cancelled-' + str(i))).exists() for i in range(3)))
        self.assertIsNone(self.process.poll())
        (self.root / 'release-workers').touch()
        self.assert_stopped()
        self.assertTrue(all((self.root / ('finished-' + str(i))).exists() for i in range(3)))
        self.assertFalse(list(self.root.glob('unexpected-*')))

    def test_stuck_background_work_has_a_logged_deadline_and_can_restart(self):
        self.start('stall')
        self.until(lambda: (self.root / 'worker-active').exists())
        self.stop()
        self.assert_stopped(1)
        self.assertIn('Shutdown deadline reached', self.log())
        self.start()
        self.stop()
        self.assert_stopped()
        self.assertEqual(len(Store(self.root / 'nas').summaries()), 1)
