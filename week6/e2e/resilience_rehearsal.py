"""Week 6 Step 7: live failure rehearsal on the local Compose stack (R1, R3, R4). Run after `make up`.

Stops and starts containers, so it is never run in CI. Standard library only; passwords are read from backend/.env
and never printed. Usage:  python3 e2e/resilience_rehearsal.py
"""

import http.cookiejar
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT, BACK = "http://127.0.0.1:3000", "http://127.0.0.1:8000"
ENV = dict(
    line.split("=", 1)
    for line in (ROOT / "backend/.env").read_text().splitlines()
    if "=" in line and not line.lstrip().startswith("#")
)
results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


def compose(*args, env=None):
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True, env=env)


jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(method, path, body=None, base=FRONT, raw=None, ctype="application/json"):
    headers = {"Accept": "application/json"}
    if method != "GET":
        headers["X-CSRFToken"] = next((c.value for c in jar if c.name == "csrftoken"), "")
        headers["Content-Type"] = ctype
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(base + path, method=method, headers=headers, data=data)
    try:
        with opener.open(req, timeout=90) as r:
            return r.status, json.loads(r.read() or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"null")
        except ValueError:
            body = None
        return e.code, body, dict(e.headers)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0, None, {}


def wait_ready(limit=120):
    for _ in range(limit):
        if call("GET", "/ready/", base=BACK)[0] == 200:
            return True
        time.sleep(1)
    return False


def code(body):
    return (body or {}).get("error", {}).get("code")


def login():
    call("GET", "/api/auth/csrf/")
    return call("POST", "/api/admin/login/", {"email": "admin@example.test", "password": ENV["SEED_ADMIN_PASSWORD"]})[0]


check("stack ready and admin signed in", wait_ready() and login() == 200)

# R1: the LLM provider is unreachable (backend restarted pointing at a closed port), then restored.
compose("up", "-d", "--no-deps", "backend", env={**__import__("os").environ, "OLLAMA_URL": "http://host.docker.internal:9"})
wait_ready()
status, body, _ = call("POST", "/api/v1/assistant/ask/", {"question": "How many times can I reschedule?"})
check(f"R1 LLM unreachable -> {status} {code(body)}", status == 503 and code(body) == "assistant_unavailable")
compose("up", "-d", "--no-deps", "backend")
wait_ready()

# R3: the database stops; the API answers a calm 503 and /ready/ reports it; then it recovers.
compose("stop", "db")
status, body, _ = call("GET", "/api/v1/clusters/")
check(f"R3 database down -> {status} {code(body)}", status == 503 and code(body) == "service_unavailable")
check("R3 backend sends Retry-After: 30", call("GET", "/api/v1/clusters/", base=BACK)[2].get("Retry-After") == "30")
check("R3 /ready/ reports 503", call("GET", "/ready/", base=BACK)[0] == 503)
compose("start", "db")
check("R3 recovers after the database returns", wait_ready() and call("GET", "/api/v1/clusters/")[0] == 200)

# R4: the worker stops; an approved document's job waits and the ops view counts it; the worker returns and finishes it.
compose("stop", "worker")
boundary = uuid.uuid4().hex
name = f"rehearsal-{boundary[:8]}.md"
text = f"# Rehearsal note {boundary[:8]}\n\nThis note exists only to rehearse a worker outage. No clinic policy.\n".encode()
form = (
    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
    f"Content-Type: text/markdown\r\n\r\n".encode()
    + text
    + f"\r\n--{boundary}--\r\n".encode()
)
status, body, _ = call(
    "POST", "/api/v1/assistant/documents/", raw=form, ctype=f"multipart/form-data; boundary={boundary}"
)
doc = (body or {}).get("id") or (body or {}).get("document", {}).get("id")
status, body, _ = call("POST", f"/api/v1/assistant/documents/{doc}/approve/", {})
job = (body or {}).get("job", {}).get("id") or (body or {}).get("id")
check(f"R4 approval accepted while the worker is down ({status})", status == 202 and job)
status, body, _ = call("GET", f"/api/v1/assistant/jobs/{job}/")
check(f"R4 job waits as queued ({(body or {}).get('status')})", (body or {}).get("status") == "queued")
queued = call("GET", "/api/v1/ops/?hours=1")[1]["jobs"]["queued"]
check(f"R4 ops view counts the queued job ({queued})", queued >= 1)
compose("start", "worker")
final = None
for _ in range(120):
    final = (call("GET", f"/api/v1/assistant/jobs/{job}/")[1] or {}).get("status")
    if final in ("succeeded", "failed"):
        break
    time.sleep(1)
check(f"R4 the returning worker finishes the job ({final})", final == "succeeded")

print(f"\n{sum(results)}/{len(results)} resilience rehearsal checks passed")
sys.exit(0 if all(results) else 1)
