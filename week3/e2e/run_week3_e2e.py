"""Real-browser checks for Week 3: the no-show estimate in the admin dashboard.

Prereqs: backend on :8000 and frontend on :3000 running, `seed_demo` done, model trained
(`python -m ml.train`, or use the committed artifact), `pip install playwright`.
Usage:  python e2e/run_week3_e2e.py <admin_password> <screenshots_dir>
"""
import sys, time
from playwright.sync_api import sync_playwright, expect

ADMIN_PW, SHOTS = sys.argv[1], sys.argv[2]
BASE = "http://127.0.0.1:3000"
results = []

def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)

def percent(page) -> float:
    return float(page.locator(".result-number").inner_text().rstrip("%"))

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{BASE}/admin/predictions"); page.wait_for_url("**/admin/login")
    check("anonymous visitor is sent to admin login", True)
    page.fill("#email", "admin@example.test"); page.fill("#password", ADMIN_PW); page.click("button:has-text('Sign in')")
    page.wait_for_url("**/admin")
    page.click("a:has-text('No-show model')"); page.wait_for_url("**/admin/predictions")
    check("dashboard links to the model page", True)

    card = page.locator("section", has=page.locator("h2", has_text="About this model"))
    expect(card.locator("tbody tr")).to_have_count(5)
    check("model card lists served model, baseline, floor and ceiling", "baseline" in card.inner_text() and "ceiling" in card.inner_text())

    page.click("button:has-text('Estimate no-show risk')")
    expect(page.locator(".result-number")).to_be_visible()
    low = percent(page)
    result_text = page.locator("section", has=page.locator("h2", has_text="Estimate")).inner_text()
    check("estimate shows probability, band and model version", "risk" in result_text and "no-show-1.0.0" in result_text)
    check("estimate shows the not-medical disclaimer", "not a medical assessment" in result_text)

    page.fill("#lead", "45"); page.select_option("#reminder", "false"); page.select_option("#age", "18-24")
    page.fill("#prior", "3"); page.fill("#missed", "3")
    page.click("button:has-text('Estimate no-show risk')")
    expect(page.locator(".badge", has_text="high risk")).to_be_visible()
    high = percent(page)
    check(f"riskier booking scores higher ({low}% -> {high}%) and is flagged high", high > low)
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=f"{SHOTS}/w3-01-no-show-estimate.png", full_page=True)

    # Field-level ranges are checked first; the cross-field rule runs once every field is valid (DRF order).
    page.fill("#hour", "3"); page.fill("#missed", "9")
    page.click("button:has-text('Estimate no-show risk')")
    expect(page.locator(".field-error", has_text="greater than or equal to 7")).to_be_visible()
    check("out-of-range hour gets a field error", True)
    check("no estimate is shown for invalid input", page.locator(".result-number").count() == 0)
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=f"{SHOTS}/w3-02-validation.png")
    page.fill("#hour", "10")
    page.click("button:has-text('Estimate no-show risk')")
    expect(page.locator(".field-error", has_text="Cannot exceed prior_appointments")).to_be_visible()
    check("no-shows > appointments gets a field error once ranges are valid", page.locator(".result-number").count() == 0)
    page.fill("#missed", "3")

    # A signed-in member (JWT cookies) must not reach the model.
    member = browser.new_context().new_page()
    member.goto(f"{BASE}/signup")
    member.fill("#name", "Week3 Member"); member.fill("#email", f"w3m{int(time.time())}@example.test")
    member.fill("#password", "Correct-Horse-9-Battery"); member.click("button:has-text('Create account')")
    member.wait_for_url("**/profile")
    r = member.request.get(f"{BASE}/api/v1/models/no-show/")
    check("signed-in member is refused by the model API (401)", r.status == 401)
    member.goto(f"{BASE}/admin/predictions"); member.wait_for_url("**/admin/login")
    check("member visiting the model page is sent to admin login", True)

    m = browser.new_context(viewport={"width": 375, "height": 740}).new_page()
    m.goto(f"{BASE}/admin/login")
    m.fill("#email", "admin@example.test"); m.fill("#password", ADMIN_PW); m.click("button:has-text('Sign in')")
    m.wait_for_url("**/admin"); m.goto(f"{BASE}/admin/predictions"); expect(m.locator("h1")).to_be_visible()
    check("no horizontal scroll on mobile", m.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    check("no uncaught JS errors", not errors)
    browser.close()

passed = sum(ok for _, ok in results)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
