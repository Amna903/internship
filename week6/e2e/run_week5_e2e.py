"""Real-browser check of Week 5 Step 5 on the Assistant tab: follow-up conversations (Playwright, through the
Next.js proxy).

Prereqs: backend on :8000 and frontend on :3000 running, `seed_demo` and `load_policies` done, the local
model running (Ollama), `pip install playwright` and `python -m playwright install chromium`.
Usage:  python e2e/run_week5_e2e.py <admin_password> <screenshots_dir>
(E2E_BASE overrides the frontend address; the backend's CSRF_TRUSTED_ORIGINS must include it.)

Covers: a question then a follow-up in one conversation (turn counter, earlier turn shown, the follow-up's
prompt budget includes earlier turns); the second request carries the signed history; neither the questions
nor the history are stored in the browser; "New conversation" resets; a tampered history is rejected by the
real server and the page starts a new conversation calmly; the conversation limit is shown calmly; phone width
without sideways scroll.
"""

import json
import os
import sys

from playwright.sync_api import expect, sync_playwright

ADMIN_PW, SHOTS = sys.argv[1], sys.argv[2]
BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:3000")
results = []


def check(name, condition):
    results.append((name, bool(condition)))
    print(("PASS " if condition else "FAIL ") + name)


def ask(page, text):
    page.fill("#question", text)
    with page.expect_response("**/api/v1/assistant/ask/", timeout=180_000) as r:
        page.click("button[type=submit]")
    expect(page.locator("[data-testid=status], [data-testid=answer] [role=alert]").first).to_be_visible(timeout=180_000)
    return r.value


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    page.goto(f"{BASE}/admin/login")
    page.fill("#email", "admin@example.test"); page.fill("#password", ADMIN_PW)
    page.click("button:has-text('Sign in')"); page.wait_for_url(f"{BASE}/admin")
    page.goto(f"{BASE}/admin/assistant")
    expect(page.locator("text=Embeddings")).to_be_visible()
    check("starts as a new conversation", "New conversation" in page.locator("[data-testid=conversation-meta]").inner_text())

    first = ask(page, "How many days do I have to request a refund?")
    check("first request carries no history", "history" not in json.loads(first.request.post_data))
    check("turn counter: question 1 of 12", "Question 1 of 12" in page.locator("[data-testid=conversation-meta]").inner_text())

    second = ask(page, "Can I do that at the front desk?")
    sent = json.loads(second.request.post_data)
    check("follow-up request carries the signed history", isinstance(sent.get("history"), str) and len(sent["history"]) > 20)
    check("turn counter: question 2 of 12", "Question 2 of 12" in page.locator("[data-testid=conversation-meta]").inner_text())
    check("earlier turn shown", "request a refund" in page.locator("[data-testid=earlier-turns]").inner_text())
    budget = page.locator("[data-testid=budget]")
    check("follow-up budget counts earlier turns",
          budget.count() == 0 or "earlier turns 0," not in budget.inner_text())  # no budget line if the model wasn't called
    page.screenshot(path=f"{SHOTS}/w5-01-follow-up.png", full_page=True)

    stored = page.evaluate("JSON.stringify(Object.assign({}, localStorage)) + JSON.stringify(Object.assign({}, sessionStorage))")
    check("questions and history not stored in the browser",
          "refund" not in stored and "front desk" not in stored and sent["history"][:20] not in stored)

    page.click("[data-testid=new-conversation]")
    check("New conversation resets", "New conversation" in page.locator("[data-testid=conversation-meta]").inner_text()
          and page.locator("[data-testid=earlier-turns]").count() == 0)

    # A tampered history goes to the REAL server, which must reject it; the page starts over calmly.
    ask(page, "How many days do I have to request a refund?")

    def tamper(route):
        body = json.loads(route.request.post_data)
        body["history"] = body["history"][:-3] + ("xyz" if not body["history"].endswith("xyz") else "abc")
        route.continue_(post_data=json.dumps(body))
    page.route("**/api/v1/assistant/ask/", tamper)
    r = ask(page, "And at the front desk?")
    page.unroute("**/api/v1/assistant/ask/")
    check("tampered history rejected by the server (400 invalid_history)",
          r.status == 400 and r.json()["error"]["code"] == "invalid_history")
    check("tampered history: calm message and a new conversation",
          "can't be continued" in page.locator("[data-testid=answer]").inner_text()
          and "New conversation" in page.locator("[data-testid=conversation-meta]").inner_text())
    page.screenshot(path=f"{SHOTS}/w5-02-tampered-history.png", full_page=True)

    page.route("**/api/v1/assistant/ask/", lambda route: route.fulfill(
        status=400, content_type="application/json",
        body='{"error": {"code": "conversation_limit", "message": "x"}}'))
    ask(page, "Where do I park?")
    page.unroute("**/api/v1/assistant/ask/")
    check("conversation limit shown calmly", "reached its limit" in page.locator("[data-testid=answer]").inner_text())

    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(f"{BASE}/admin/assistant"); page.wait_for_load_state("networkidle")
    check("no sideways scroll at phone width",
          page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth"))
    page.screenshot(path=f"{SHOTS}/w5-03-assistant-phone.png", full_page=True)
    browser.close()

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
