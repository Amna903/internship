"""Week 6 Step 12: the live end-to-end demo in a real browser, against the Compose stack (`make up`).

signup → profile → prediction → clusters → cited answer → agent tool call → human approval → audit trail.
Real local model (Ollama). Passwords are read from backend/.env and never printed. Screenshots go to
docs/screenshots/w6-*.png. Usage:  python e2e/demo_week6.py   (E2E_BASE overrides http://127.0.0.1:3000)
"""

import os
import sys
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(
    line.split("=", 1)
    for line in (ROOT / "backend/.env").read_text().splitlines()
    if "=" in line and not line.lstrip().startswith("#")
)
BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:3000")
SHOTS = ROOT / "docs" / "screenshots"
EMAIL = f"demo-{uuid.uuid4().hex[:8]}@example.test"
MEMBER_PW = "Demo-" + uuid.uuid4().hex  # a throwaway synthetic account
results = []


def check(name, condition):
    results.append(bool(condition))
    print(("PASS " if condition else "FAIL ") + name, flush=True)


def shot(page, name):
    page.screenshot(path=str(SHOTS / f"w6-{name}.png"), full_page=True)


def run_agent(page, message):
    page.fill("#agent-message", message)
    with page.expect_response("**/api/v1/agent/run/", timeout=240_000) as r:
        page.click("button[type=submit]")
    expect(page.locator("[data-testid=agent-status], [data-testid=agent-result] [role=alert]").first).to_be_visible(
        timeout=240_000
    )
    page.wait_for_timeout(500)
    return r.value.json()


with sync_playwright() as p:
    browser = p.chromium.launch()

    # 1–2. A member signs up and fills in their profile.
    member = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()
    member.goto(f"{BASE}/signup")
    member.fill("#name", "Demo Member")
    member.fill("#email", EMAIL)
    member.fill("#password", MEMBER_PW)
    member.click("button:has-text('Create account')")
    member.wait_for_url("**/profile")
    check("1 signup: the new member lands on their profile", True)
    member.select_option("#agemode", "range")
    member.select_option("#range", "25-34")
    member.fill("#goals", "Walk more")
    member.click("button:has-text('Save profile')")
    expect(member.locator(".alert.ok")).to_be_visible()
    check("2 profile saved", True)
    shot(member, "01-profile")

    # Admin signs in.
    page = browser.new_context(viewport={"width": 1280, "height": 1000}).new_page()
    page.goto(f"{BASE}/admin/login")
    page.fill("#email", "admin@example.test")
    page.fill("#password", ENV["SEED_ADMIN_PASSWORD"])
    page.click("button:has-text('Sign in')")
    page.wait_for_url(f"{BASE}/admin")
    page.fill("[aria-label='Search name or email']", EMAIL)
    expect(page.locator("table tbody tr", has_text="Demo Member")).to_have_count(1)
    check("admin sees the new member's profile", True)

    # 3. Prediction.
    page.goto(f"{BASE}/admin/predictions")
    page.click("button:has-text('Estimate')")
    expect(page.locator(".estimate-result .suggestion")).to_be_visible(timeout=30_000)
    check(
        "3 prediction: suggestion, version and disclaimer",
        "1.0.0" in page.locator(".estimate-result").inner_text()
        and "medical" in page.locator(".estimate-result [data-testid=disclaimer]").inner_text().lower(),
    )
    shot(page, "02-prediction")

    # 4. Clusters.
    page.goto(f"{BASE}/admin/clusters")
    expect(page.locator("[data-testid=pca-plot]")).to_be_visible(timeout=30_000)
    check("4 clusters: real-data verdict and disclaimer", "No reliable structure" in page.locator(
        "[data-testid=real-verdict]").inner_text())
    shot(page, "03-clusters")

    # 5. Cited answer.
    page.goto(f"{BASE}/admin/assistant")
    page.click("button:has-text('Answerable')")
    expect(page.locator("[data-testid=status]")).to_be_visible(timeout=180_000)
    status = page.locator("[data-testid=status]").inner_text()
    check(f"5 assistant: cited answer ({status}, {page.locator('[data-testid=citation]').count()} citation(s))",
          status == "Answer" and page.locator("[data-testid=citation]").count() >= 1)
    shot(page, "04-cited-answer")

    # 6–7. Agent tool call, then human approval.
    page.goto(f"{BASE}/admin/agent")
    card = page.locator("[data-testid=approval-card]")
    for attempt in range(3):  # the local model sometimes asks a question first; same request, at most 3 tries
        run = run_agent(page, "Please book the first telehealth slot on Thursday morning.")
        if card.count():
            break
    tools = [s.get("tool") for s in run.get("steps", []) if s.get("tool") and s.get("code") == "ok"]
    check(f"6 agent tool calls: {' → '.join(tools) or 'none'} (attempt {attempt + 1})", card.count() == 1)
    shot(page, "05-agent-proposal")
    if card.count():
        page.click("[data-testid=confirm]")
        expect(page.locator("[data-testid=card-status]")).to_have_text("confirmed", timeout=20_000)
        check("7 human approval: confirmed, fictional booking shown", "Booked (fictional)" in card.inner_text())
        shot(page, "06-approved")
    else:
        check("7 human approval: no proposal to approve", False)

    # 8. Audit trail and operations.
    page.goto(f"{BASE}/admin/audit")
    expect(page.locator("[data-testid=audit-runs]")).to_be_visible(timeout=20_000)
    approvals = page.locator("[data-testid=audit-approvals]").inner_text()
    check("8 audit trail: agent run, the confirmed approval and the ops tables",
          "confirmed" in approvals and page.locator("[data-testid=ops-routes]").count() == 1)
    text = page.locator("main").inner_text()
    check("audit page holds no member email or question text",
          EMAIL not in text and "How many times can I reschedule" not in text)
    shot(page, "07-audit")
    browser.close()

print(f"\n{sum(results)}/{len(results)} demo checks passed")
sys.exit(0 if all(results) else 1)
