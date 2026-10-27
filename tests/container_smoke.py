"""Run against the ephemeral CI container, never against a user's NAS."""
import json
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

for attempt in range(30):
    try:
        with urlopen(Request("http://127.0.0.1:8789/api/health", headers={"Host": "studio.example"}), timeout=2) as response:
            health = json.load(response)
        assert health["ready"] and health["mode"] == "server"
        break
    except (URLError, OSError):
        time.sleep(1)
else:
    raise SystemExit("Container did not become ready")
try:
    urlopen(Request("http://127.0.0.1:8789/api/projects", headers={"Host": "studio.example"}), timeout=2)
    raise AssertionError("Unauthenticated project access was allowed")
except HTTPError as error:
    assert error.code == 401
    error.close()
print("Container boots, FFmpeg is ready, project access requires authentication.")

code = subprocess.check_output(["docker", "exec", "studio-ci", "cat", "/data/setup-code"], text=True).strip()
payload = json.dumps({"username": "ci-owner", "password": "ci-only-long-password", "code": code}).encode()
request = Request("http://127.0.0.1:8789/api/auth/setup", data=payload, headers={"Host": "studio.example", "Content-Type": "application/json"})
with urlopen(request, timeout=10) as response:
    cookie = response.headers["Set-Cookie"].split(";")[0]
    owner = json.load(response)
assert owner["role"] == "owner"
for route in ("projects", "catalog"):
    with urlopen(Request("http://127.0.0.1:8789/api/" + route, headers={"Host": "studio.example", "Cookie": cookie}), timeout=3) as response:
        assert json.load(response) == [], "Private content was bundled in the image"
print("First owner setup works; public image has no private projects or subtitle archive.")

# Persist a synthetic project, then exercise the production entry point and
# Docker's stop signal. A successful `docker stop` alone can conceal SIGKILL.
payload = json.dumps({'text':json.dumps({'name':'Shutdown persistence fixture', 'segments':[
    {'startMs':0,'endMs':1000,'text':'Synthetic persistence check.'}]})}).encode()
request = Request('http://127.0.0.1:8789/api/import', data=payload, headers={
    'Host':'studio.example','Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':owner['csrf']})
with urlopen(request, timeout=5) as response:
    project = json.load(response)

def ready():
    for attempt in range(30):
        try:
            with urlopen(Request('http://127.0.0.1:8789/api/health', headers={'Host':'studio.example'}), timeout=2) as response:
                assert json.load(response)['ready']
            return
        except OSError:
            time.sleep(.2)
    raise AssertionError('Container did not restart')

def stop(name):
    before = time.monotonic()
    subprocess.run(['docker','stop','-t','30',name], check=True, timeout=40)
    elapsed = time.monotonic() - before
    state = json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',name]))
    assert state['Status'] == 'exited' and state['ExitCode'] == 0, state
    assert elapsed < 25, f'Stop took {elapsed:.1f}s, approaching Docker forced termination'
    logs = subprocess.check_output(['docker','logs',name], stderr=subprocess.STDOUT, text=True)
    assert 'Shutdown requested (SIGTERM)' in logs and 'Shutdown complete.' in logs
    assert 'Shutdown deadline reached' not in logs

stop('studio-ci')
subprocess.run(['docker','start','studio-ci'], check=True, timeout=10)
ready()
request = Request('http://127.0.0.1:8789/api/auth/login', data=json.dumps({
    'username':'ci-owner','password':'ci-only-long-password'}).encode(),
    headers={'Host':'studio.example','Content-Type':'application/json'})
with urlopen(request, timeout=5) as response:
    cookie = response.headers['Set-Cookie'].split(';')[0]
request = Request('http://127.0.0.1:8789/api/projects/' + project['id'], headers={'Host':'studio.example','Cookie':cookie})
with urlopen(request, timeout=5) as response:
    assert json.load(response)['segments'] == project['segments']

# Browser preconnections/incomplete headers must not hold shutdown open.
with socket.create_connection(('127.0.0.1',8789), timeout=3) as idle:
    idle.sendall(b'GET /api/health HTTP/1.1\r\nHost: studio.example\r\n')
    time.sleep(.1)
    stop('studio-ci')

# Also verify signal handling when Python is PID 1 in a direct Docker run.
subprocess.run(['docker','run','-d','--name','studio-no-init','--read-only','--tmpfs','/tmp:size=512m',
    '--cap-drop','ALL','--security-opt','no-new-privileges:true','-v','studio-ci-data:/data',
    '-e','STUDIO_PUBLIC_URL=https://studio.example','-p','127.0.0.1:8789:8787','breathwork-ci'],check=True,timeout=30)
ready()
stop('studio-no-init')
print('TERM exits 0 with/without init and idle sockets; restart preserves the owner and subtitle project.')
