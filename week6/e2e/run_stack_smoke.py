"""Week 6 Step 1: smoke test of the containerised stack (`make up`) in a real browser, with the real local model.

Usage:  python e2e/run_stack_smoke.py <admin_password> <screenshots_dir>    (E2E_BASE defaults to :3000)
Covers: admin sign-in, a prediction, the clusters page, a cited assistant answer, an agent run, and /ready/.
The model can vary; every check prints PASS or FAIL as it came out.
"""

import os
import sys

from playwright.sync_api import expect, sync_playwright

ADMIN_PW, SHOTS = sys.argv[1], sys.argv[2]
BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:3000")
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


# E2E_INSECURE=1 for the HTTPS rehearsal, whose certificate comes from Caddy's internal (self-signed) CA.
INSECURE = os.environ.get("E2E_INSECURE") == "1"
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--host-resolver-rules=MAP *.localhost 127.0.0.1"])
    page = browser.new_page(viewport={"width": 1280, "height": 1000}, ignore_https_errors=INSECURE)
    # Through the browser's own resolver (it maps *.localhost to loopback; Python's doesn't).
    check("/ready/ returns 200", page.goto(f"{API}/ready/").status == 200)
    page.goto(f"{BASE}/admin/login")
    page.fill("#email", "admin@example.test"); page.fill("#password", ADMIN_PW)
    page.click("button:has-text('Sign in')")
    page.wait_for_url(f"{BASE}/admin", timeout=30_000)
    check("admin signs in", page.url.endswith("/admin"))

    page.goto(f"{BASE}/admin/predictions")
    page.click("button:has-text('Estimate')")
    expect(page.locator("[data-testid=disclaimer]")).to_be_visible(timeout=30_000)
    check("prediction shown with its disclaimer", True)

    page.goto(f"{BASE}/admin/clusters")
    expect(page.locator("[data-testid=pca-plot]")).to_be_visible(timeout=30_000)
    check("clusters page shows the PCA plot", True)

    page.goto(f"{BASE}/admin/assistant")
    page.fill("#question", "How many times can I reschedule an appointment?")
    with page.expect_response("**/api/v1/assistant/ask/", timeout=180_000) as r:
        page.click("button[type=submit]")
    answer = r.value.json()
    check(f"assistant answers with a citation (status {answer.get('status')})",
          answer.get("status") == "answered" and bool(answer.get("citations")))
    page.screenshot(path=f"{SHOTS}/w6-01-stack-assistant.png", full_page=True)

    page.goto(f"{BASE}/admin/agent")
    page.fill("#agent-message", "Please book the first telehealth slot on Thursday morning.")
    with page.expect_response("**/api/v1/agent/run/", timeout=240_000) as r:
        page.click("button[type=submit]")
    run = r.value.json()
    check(f"agent run ends calmly ({run.get('status')}, {run.get('tool_calls')} tool calls)",
          run.get("status") in ("done", "stopped") and run.get("tool_calls", 9) <= 4)
    page.wait_for_timeout(1000)
    page.screenshot(path=f"{SHOTS}/w6-02-stack-agent.png", full_page=True)
    browser.close()

print(f"\n{sum(results)}/{len(results)} stack checks passed")
sys.exit(0 if all(results) else 1)
