"""Week 5 Step 10 (J1–J3): the indexing job on a REAL Celery worker process and a REAL Redis broker.

Everything runs in subprocesses against a temporary SQLite file, as a deployment would: `manage.py` queues the
job (published to Redis), a separate `celery worker` process picks it up, and the test reads the job's state
from the database. Fault injection is the test-only flaky embedder (ASSISTANT_EMBEDDER=flaky).

- Phase 1: the job is queued with no worker running (state "queued", 0 attempts, really sitting in Redis). A
  worker whose embedder fails once then starts: the job retries and succeeds (2 attempts).
- Phase 2: a worker whose embedder always fails: the job fails after exactly 3 attempts, the version stays
  pending and the first document is untouched.

Skipped when Redis isn't reachable, unless REQUIRE_REDIS=1 (set in CI, which runs a Redis service), where a
missing Redis is a failure instead, so CI can never pass with this test skipped.
"""

import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REDIS_URL = os.environ.get("REDIS_TEST_URL", "redis://localhost:6379/15")


def redis_up() -> bool:
    url = urlparse(REDIS_URL)
    try:
        with socket.create_connection((url.hostname, url.port or 6379), timeout=1) as s:
            s.sendall(b"PING\r\n")
            return s.recv(16).startswith(b"+PONG")
    except OSError:
        return False


if not redis_up():
    if os.environ.get("REQUIRE_REDIS") == "1":
        pytest.fail(f"REQUIRE_REDIS=1 but Redis is not reachable at {REDIS_URL}", pytrace=False)
    pytest.skip(
        "Redis is not running (brew services start redis); CI runs this test with REQUIRE_REDIS=1",
        allow_module_level=True,
    )

SETUP = """
import hashlib
from accounts.models import User
from assistant.documents import create_document
admin = User.objects.create_admin('worker@example.test', '{password}')
for name, text in [('refunds.md', 'A refund can be requested within 14 days of a payment.'),
                   ('parking.md', 'Parking at the clinic is free for visitors with a ticket.')]:
    create_document(name, text, hashlib.sha256(text.encode()).hexdigest(), 'upload', admin, policy_area='other')
"""
QUEUE = """
from accounts.models import User
from assistant.jobs import queue_approval
from assistant.models import DocumentVersion
v = DocumentVersion.objects.get(document__filename='{name}')
job, created = queue_approval(v, User.objects.get(email='worker@example.test'), 'worker-test')
print(job.id)
"""


@pytest.fixture
def deployment(tmp_path):
    from .conftest import PASSWORD

    db = tmp_path / "jobs.sqlite3"
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings_test",
        "DATABASE_URL": f"sqlite:///{db}",
        "CELERY_TASK_ALWAYS_EAGER": "false",
        "CELERY_BROKER_URL": REDIS_URL,
        "CELERY_QUEUE": f"test-{uuid.uuid4().hex[:12]}",
        "INDEX_JOB_BACKOFF": "1,1",
        "ASSISTANT_EMBEDDER": "flaky",
    }

    def manage(*args):
        return subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=BACKEND,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout

    def queue(name):
        return int(manage("shell", "-c", QUEUE.format(name=name)).strip().splitlines()[-1])

    def state(job_id):
        with sqlite3.connect(db) as conn:
            return conn.execute(
                "SELECT status, attempts, error_code FROM assistant_indexjob WHERE id = ?", (job_id,)
            ).fetchone()

    def version_status(name):
        with sqlite3.connect(db) as conn:
            return conn.execute(
                "SELECT v.status FROM assistant_documentversion v JOIN assistant_policydocument d "
                "ON d.id = v.document_id WHERE d.filename = ?",
                (name,),
            ).fetchone()[0]

    workers = []

    def start_worker(failures: int):
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "config",
                "worker",
                "--pool=solo",
                "-Q",
                env["CELERY_QUEUE"],
                "--without-heartbeat",
                "--without-gossip",
                "--without-mingle",
                "-l",
                "warning",
            ],
            cwd=BACKEND,
            env={**env, "ASSISTANT_FLAKY_FAILURES": str(failures)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        workers.append(worker)
        return worker

    def stop_worker(worker):
        worker.terminate()
        try:
            worker.wait(timeout=20)
        except subprocess.TimeoutExpired:
            worker.kill()

    def wait_for(job_id, done=("succeeded", "failed"), seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            row = state(job_id)
            if row and row[0] in done:
                return row
            time.sleep(0.25)
        pytest.fail(f"job {job_id} still {state(job_id)} after {seconds} s")

    manage("migrate", "-v0")
    manage("shell", "-c", SETUP.format(password=PASSWORD))
    yield type(
        "Deployment",
        (),
        dict(
            queue=staticmethod(queue),
            state=staticmethod(state),
            version_status=staticmethod(version_status),
            start_worker=staticmethod(start_worker),
            stop_worker=staticmethod(stop_worker),
            wait_for=staticmethod(wait_for),
        ),
    )
    for w in workers:
        if w.poll() is None:
            stop_worker(w)


def test_a_real_worker_retries_a_transient_failure_and_bounds_a_permanent_one(deployment):
    # Phase 1: queued in Redis with no worker running, then a worker whose embedder fails once.
    first = deployment.queue("refunds.md")
    time.sleep(1)
    assert deployment.state(first) == ("queued", 0, "")
    worker = deployment.start_worker(failures=1)
    assert deployment.wait_for(first) == ("succeeded", 2, "")  # 2 attempts: the first failed and was retried
    assert deployment.version_status("refunds.md") == "current"
    deployment.stop_worker(worker)

    # Phase 2: a worker whose embedder never recovers. Bounded: exactly 3 attempts, then failed; nothing changed.
    second = deployment.queue("parking.md")
    worker = deployment.start_worker(failures=99)
    assert deployment.wait_for(second) == ("failed", 3, "unavailable")
    assert deployment.version_status("parking.md") == "pending"
    assert deployment.version_status("refunds.md") == "current"
    deployment.stop_worker(worker)
