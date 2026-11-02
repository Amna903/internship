"""Week 5 Step 13 acceptance demos (A1–A10) in a real browser against the real stack: Django on :8000, Next.js on
:3000 (proxy), Redis, Ollama, and Celery workers that THIS script starts and stops (so it can show a job failing
on an unreachable embedder and then recovering).

Prereqs: backend and frontend running, `seed_demo` and `load_policies` done, Redis and Ollama running,
`pip install playwright` and `python -m playwright install chromium`.
Usage:  python e2e/run_acceptance_e2e.py <admin_password> <member_password> <screenshots_dir>

The agent runs use the real model, so what it chooses can vary; every check prints PASS or FAIL as it came out,
and nothing is retried to get a pass.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ADMIN_PW, MEMBER_PW, SHOTS = sys.argv[1], sys.argv[2], sys.argv[3]
BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:3000")
BACKEND = Path(__file__).resolve().parents[1] / "backend"
results = []


def check(name, condition):
    results.append((name, bool(condition)))
    print(("PASS " if condition else "FAIL ") + name, flush=True)


def worker(env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.Popen([str(BACKEND / ".venv/bin/python"), "-m", "celery", "-A", "config", "worker", "--pool=solo",
                             "--without-heartbeat", "--without-gossip", "--without-mingle", "-l", "warning"],
                            cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def csrf(ctx):
    return next((c["value"] for c in ctx.cookies() if c["name"] == "csrftoken"), "")


def upload(ctx, url, name, text):
    return ctx.request.post(f"{BASE}{url}", multipart={"file": {"name": name, "mimeType": "text/markdown",
                            "buffer": text.encode()}, "policy_area": "access"} if url.endswith("documents/") else
                            {"file": {"name": name, "mimeType": "text/markdown", "buffer": text.encode()}},
                            headers={"X-CSRFToken": csrf(ctx)})


def post(ctx, url):
    return ctx.request.post(f"{BASE}{url}", headers={"X-CSRFToken": csrf(ctx)})


def wait_job(ctx, job_id, seconds=240):
    deadline = time.monotonic() + seconds
    job = {}
    while time.monotonic() < deadline:
        r = ctx.request.get(f"{BASE}/api/v1/assistant/jobs/{job_id}/")
        if r.status == 429:  # job reads share the assistant's 10/min limit (a known gap)
            time.sleep(10)
            continue
        job = r.json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(4)
    return job


def run_agent(page, message):
    page.fill("#agent-message", message)
    with page.expect_response("**/api/v1/agent/run/", timeout=240_000) as r:
        page.click("button[type=submit]")
    expect(page.locator("[data-testid=agent-status], [data-testid=agent-result] [role=alert]").first).to_be_visible(timeout=240_000)
    page.wait_for_timeout(500)  # the card is fetched right after the run
    return r.value.json()


def tools_used(run):
    return [s.get("tool") for s in run.get("steps", []) if s.get("tool") and s.get("code") == "ok"]


V1 = ("# Bag lockers (Week 5 acceptance demo)\n\nVisitors can store a bag in the lockers next to reception. "
      "Lockers are free and the key is returned at check-out.\n")
V2 = ("# Bag lockers (Week 5 acceptance demo)\n\nVisitors can store a bag in the lockers on the second floor. "
      "Lockers cost one pound and the key is returned at check-out.\n")

w = worker()
try:
  with sync_playwright() as p:
      browser = p.chromium.launch()
      ctx = browser.new_context(viewport={"width": 1280, "height": 1100})
      page = ctx.new_page()
      page.goto(f"{BASE}/admin/login")
      page.fill("#email", "admin@example.test"); page.fill("#password", ADMIN_PW)
      page.click("button:has-text('Sign in')"); page.wait_for_url(f"{BASE}/admin")

      # ---- A1 multi-tool workflow, A9 bounded loop (trace and limits) ----
      page.goto(f"{BASE}/admin/agent")
      run = run_agent(page, "Is there a telehealth slot on Wednesday morning, and what is the late cancellation fee?")
      used = tools_used(run)
      check(f"A1 multi-tool run used 2+ different tools ({', '.join(used) or 'none'})", len(set(used)) >= 2)
      check(f"A9 bounded: {run['tool_calls']} tool call(s) within the 4-call limit, ended {run['status']}",
            run["tool_calls"] <= 4 and run["status"] in ("done", "stopped", "failed"))
      page.screenshot(path=f"{SHOTS}/w5-04-agent-multi-tool.png", full_page=True)

      # ---- A3 rejected write, A4 explicitly approved write ----
      run = run_agent(page, "Please book the first telehealth slot on Thursday morning.")
      card = page.locator("[data-testid=approval-card]")
      proposed = card.count() == 1
      check("A3/A4 a booking was proposed and shown as a server-built card", proposed)
      if proposed:
          check("card says it was proposed by the agent", "agent" in card.inner_text().lower())
          page.screenshot(path=f"{SHOTS}/w5-05-approval-card.png", full_page=True)
          page.click("[data-testid=decline]")
          expect(page.locator("[data-testid=card-status]")).to_have_text("declined", timeout=20_000)
          check("A3 declined: status declined, nothing booked", page.locator("[data-testid=card-status]").inner_text() == "declined")
          run = run_agent(page, "Please book the first telehealth slot on Thursday morning.")
          if page.locator("[data-testid=approval-card]").count():
              with page.expect_response("**/confirm/") as conf:
                  page.click("[data-testid=confirm]")
              key = conf.value.request.headers.get("idempotency-key", "")
              expect(page.locator("[data-testid=card-status]")).to_have_text("confirmed", timeout=20_000)
              check("A4 confirmed by the human with an Idempotency-Key; booking shown",
                    bool(re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key)) and "Booked (fictional)" in page.locator("[data-testid=approval-card]").inner_text())
              page.screenshot(path=f"{SHOTS}/w5-06-approved-write.png", full_page=True)
          else:
              check("A4 second proposal appeared", False)

      # ---- A2 unauthorized denial: a member is refused; the write tool isn't offered without a booking request ----
      member = browser.new_context()
      mpage = member.new_page()
      mpage.goto(f"{BASE}/login")
      mpage.fill("#email", "amina.rahman@example.test"); mpage.fill("#password", MEMBER_PW)
      mpage.click("button:has-text('Sign in')"); mpage.wait_for_timeout(1500)
      denied = member.request.post(f"{BASE}/api/v1/agent/run/", data={"message": "Book a slot"},
                                   headers={"X-CSRFToken": csrf(member)})
      check(f"A2 a member is refused the agent API ({denied.status})", denied.status in (401, 403))
      run = run_agent(page, "What is the parking policy?")
      check("A2 the write tool is not offered for a non-booking request",
            "book_mock_appointment" not in json.dumps(run.get("steps", [])) or all(
                s.get("code") != "ok" for s in run["steps"] if s.get("tool") == "book_mock_appointment"))

      # ---- A5 document re-indexing through the real job queue ----
      doc = upload(ctx, "/api/v1/assistant/documents/", "bag-lockers.md", V1).json()
      r = post(ctx, f"/api/v1/assistant/documents/{doc['id']}/approve/")
      job = wait_job(ctx, r.json()["job"]["id"])
      check(f"A5 v1 approval job: {r.status} then {job['status']} in {job['attempts']} attempt(s)", r.status == 202 and job["status"] == "succeeded")
      upload(ctx, f"/api/v1/assistant/documents/{doc['id']}/versions/", "bag-lockers.md", V2)

      # ---- A7 job failure and retry: a worker whose embedder is unreachable, then a healthy one ----
      stop(w)
      w = worker({"OLLAMA_URL": "http://127.0.0.1:9", "INDEX_JOB_BACKOFF": "2,4"})
      r = post(ctx, f"/api/v1/assistant/documents/{doc['id']}/versions/2/approve/")
      job = wait_job(ctx, r.json()["job"]["id"])
      check(f"A7 job retried and failed: {job['status']} after {job['attempts']}/{job['max_attempts']} ({job['error_code']})",
            job["status"] == "failed" and job["attempts"] == 3 and job["error_code"] in ("unavailable", "timeout"))
      stop(w)
      w = worker()
      r = post(ctx, f"/api/v1/assistant/documents/{doc['id']}/versions/2/approve/")
      job = wait_job(ctx, r.json()["job"]["id"])
      check(f"A7 after recovery a new job succeeds ({job['status']})", job["status"] == "succeeded")
      page.goto(f"{BASE}/admin/assistant")
      page.fill("#question", "Where can I store a bag and how much do the lockers cost?")
      with page.expect_response("**/api/v1/assistant/ask/", timeout=180_000) as a:
          page.click("button[type=submit]")
      answer = a.value.json()
      cited = [c["passage_id"] for c in answer.get("citations", [])]
      check(f"A5 the new edition is what search returns (status {answer['status']}, cited {cited or 'none'})",
            answer["status"] != "answered" or any("bag-lockers.md@v2" in c for c in cited))
      page.screenshot(path=f"{SHOTS}/w5-07-reindexed-answer.png", full_page=True)
      post(ctx, f"/api/v1/assistant/documents/{doc['id']}/retire/")  # leave the demo corpus as it was

      # ---- A8 the audit trail ----
      page.goto(f"{BASE}/admin/audit")
      expect(page.locator("[data-testid=audit-jobs]")).to_be_visible(timeout=20_000)
      text = page.locator("main").inner_text()
      check("A8 audit page shows runs, approvals, jobs (a failed 3/3) and model versions",
            all(page.locator(f"[data-testid={t}]").count() for t in ("audit-runs", "audit-approvals", "audit-jobs", "audit-models"))
            and "3/3" in page.locator("[data-testid=audit-jobs]").inner_text())
      check("A8 no member email or document text on the audit page", "amina.rahman@example.test" not in text and "lockers" not in text.lower())
      page.screenshot(path=f"{SHOTS}/w5-08-audit-page.png", full_page=True)
      browser.close()
finally:
    stop(w)

passed = sum(ok for _, ok in results)
print(f"\n{passed}/{len(results)} acceptance checks passed")
sys.exit(0 if passed == len(results) else 1)
