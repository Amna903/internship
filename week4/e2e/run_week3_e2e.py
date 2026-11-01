"""Real-browser check of the Week 3 no-show estimate page (Playwright, through the Next.js proxy).

Prereqs: backend on :8000 and frontend on :3000 running, `seed_demo` done, `pip install playwright`
and `python -m playwright install chromium`.
Usage:  python e2e/run_week3_e2e.py <admin_password> <member_password> <screenshots_dir>

Covers: admin reaches the page from the dashboard; both suggestions via the "Fill example" buttons, with
the disclaimer and model version beside the result; an edit clears the old result; browser checks;
server 400s shown next to fields; a 503 shown calmly with the form kept; no alarming words on the page;
phone width without sideways scroll; logged-out and member visitors are sent to the admin login, and
the API itself refuses a member.
"""

import json
import os
import sys

from playwright.sync_api import expect, sync_playwright

ADMIN_PW, MEMBER_PW, SHOTS = sys.argv[1], sys.argv[2], sys.argv[3]
BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:3000")
PAGE = f"{BASE}/admin/predictions"
results = []


def check(name, condition):
    results.append((name, bool(condition)))
    print(("PASS " if condition else "FAIL ") + name)


def result_text(page):
    return page.locator(".estimate-result").inner_text()


with sync_playwright() as p:
    browser = p.chromium.launch()

    # ---------------- admin ----------------
    ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    page.goto(f"{BASE}/admin/login")
    page.fill("#email", "admin@example.test"); page.fill("#password", ADMIN_PW)
    page.click("button:has-text('Sign in')"); page.wait_for_url(f"{BASE}/admin")
    page.click("text=ML tools"); page.wait_for_url(PAGE)
    check("admin reaches the page from the dashboard link", page.url == PAGE)
    expect(page.locator(".model-card")).to_be_visible()

    # Example: far ahead -> extra reminder
    page.click("text=Booked 60 days ahead, no reminder, past misses")
    page.click("button:has-text('Estimate')")
    expect(page.locator(".suggestion")).to_have_text("Extra reminder suggested")
    text = result_text(page)
    check("far-ahead example -> 'Extra reminder suggested'", "Extra reminder suggested" in text)
    check("disclaimer shown beside the result", page.locator("[data-testid=disclaimer]").is_visible()
          and "Not a medical assessment" in page.locator("[data-testid=disclaimer]").inner_text())
    check("model version shown", "Model no-show-1.0.0" in text)
    page.locator(".model-card summary").click()
    page.screenshot(path=f"{SHOTS}/w3-01-estimate-extra-reminder.png", full_page=True)

    # Editing clears the old result (no stale estimate next to new inputs)
    page.fill("#lead_time_days", "59")
    check("changing an input clears the previous result", page.locator(".suggestion").count() == 0)

    # Example: next day -> standard reminder
    page.click("text=Next-day, reminder sent")
    page.click("button:has-text('Estimate')")
    expect(page.locator(".suggestion")).to_have_text("Standard reminder")
    check("next-day example -> 'Standard reminder'", True)
    page.screenshot(path=f"{SHOTS}/w3-02-estimate-standard-reminder.png", full_page=True)

    # Browser-side checks (no request sent)
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "/predictions/" in r.url else None)
    page.fill("#appointment_hour", "22")
    page.fill("#prior_appointments", "2"); page.fill("#prior_no_shows", "3")
    page.click("button:has-text('Estimate')")
    check("out-of-range hour shown next to the field", "between 7 and 19" in page.locator("#appointment_hour-error").inner_text())
    check("more missed than earlier appointments shown", page.locator("#prior_no_shows-error").is_visible())
    check("invalid form sends no request", requests == [])
    page.screenshot(path=f"{SHOTS}/w3-03-form-validation.png", full_page=True)

    # Server is the authority: a body the browser checks would accept, altered in flight -> server 400
    page.click("text=Next-day, reminder sent")

    def tamper(route):
        body = json.loads(route.request.post_data); body["appointment_hour"] = 22
        route.continue_(post_data=json.dumps(body))
    page.route("**/api/v1/predictions/no-show/", tamper)
    page.click("button:has-text('Estimate')")
    expect(page.locator("#appointment_hour-error")).to_be_visible()
    check("server 400 shown next to the matching field", "19" in page.locator("#appointment_hour-error").inner_text())
    page.unroute("**/api/v1/predictions/no-show/")

    # Model unavailable -> calm message, form kept
    page.click("text=Next-day, reminder sent")
    page.route("**/api/v1/predictions/no-show/", lambda r: r.fulfill(status=503, content_type="application/json", body=json.dumps(
        {"error": {"code": "model_unavailable", "message": "The estimate service is temporarily unavailable.", "details": {}}})))
    page.click("button:has-text('Estimate')")
    expect(page.locator(".alert")).to_contain_text("temporarily unavailable")
    check("503 shown as a calm 'temporarily unavailable' message", True)
    check("form values kept after a 503", page.input_value("#lead_time_days") == "1")
    page.screenshot(path=f"{SHOTS}/w3-04-model-unavailable.png", full_page=True)
    page.unroute("**/api/v1/predictions/no-show/")

    # Nothing alarming or clinical anywhere on the page
    page.click("text=Booked 60 days ahead, no reminder, past misses"); page.click("button:has-text('Estimate')")
    expect(page.locator(".suggestion")).to_be_visible()
    visible = page.locator("main").inner_text().lower()
    check("no 'risk' / 'high' / diagnosis words on the page",
          not any(w in visible for w in ("risk", "high", "diagnos", "disease", "illness")))

    # Phone width
    page.set_viewport_size({"width": 390, "height": 900}); page.reload()
    page.click("text=Booked 60 days ahead, no reminder, past misses"); page.click("button:has-text('Estimate')")
    expect(page.locator(".suggestion")).to_be_visible()
    no_scroll = page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")
    check("phone width: no sideways scroll", no_scroll)
    page.screenshot(path=f"{SHOTS}/w3-05-mobile.png", full_page=True)
    ctx.close()

    # ---------------- logged out ----------------
    anon = browser.new_context().new_page()
    anon.goto(PAGE); anon.wait_for_url("**/admin/login")
    check("logged-out visitor is sent to the admin login", anon.url.endswith("/admin/login"))

    # ---------------- member ----------------
    member = browser.new_context().new_page()
    member.goto(f"{BASE}/login")
    member.fill("#email", "amina.rahman@example.test"); member.fill("#password", MEMBER_PW)
    member.click("button:has-text('Sign in')"); member.wait_for_url("**/profile")
    member.goto(PAGE); member.wait_for_url("**/admin/login")
    check("member visiting the page is sent to the admin login", member.url.endswith("/admin/login"))
    api = member.request.post(f"{BASE}/api/v1/predictions/no-show/", data={"lead_time_days": 1})
    check("member's direct API request is refused (401/403)", api.status in (401, 403))

    browser.close()

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
