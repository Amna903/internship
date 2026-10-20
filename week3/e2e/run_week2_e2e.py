"""Week 2 acceptance checks in a real browser (Playwright). Frontend only: no backend needed.

Prereqs: `pip install playwright && playwright install chromium`, frontend running
(`npm run build && npm start`, or `npm run dev`).
Usage:  python e2e/run_week2_e2e.py [base_url] [screenshots_dir]
        defaults: http://127.0.0.1:3000  docs/screenshots
"""
import re, sys
from playwright.sync_api import sync_playwright, expect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000"
SHOTS = sys.argv[2] if len(sys.argv) > 2 else "docs/screenshots"
results = []

def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)

def count(page):
    return page.locator(".pro-grid > li").count()

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1200, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # ---------- Directory: list, filters, URL persistence ----------
    page.goto(f"{BASE}/professionals")
    total = count(page)
    check(f"list renders all professionals from JSON ({total})", total >= 12)
    page.screenshot(path=f"{SHOTS}/w2-01-directory.png", full_page=True)

    page.get_by_role("checkbox", name="Nutrition & dietetics").check()
    page.wait_for_url(re.compile(r"specialty=nutrition"))
    page.select_option("#location", "lahore")
    page.wait_for_url(re.compile(r"location=lahore"))
    combined = count(page)
    check("filters combine (specialty AND location) and narrow the list", 0 < combined < total)
    check("URL reflects every active filter", "specialty=nutrition" in page.url and "location=lahore" in page.url)

    page.select_option("#sort", "fee_desc")
    page.wait_for_url(re.compile(r"sort=fee_desc"))
    fees = [int(re.sub(r"\D", "", t)) for t in page.locator(".fee").all_inner_texts()]
    check("sort by fee (high to low) orders results", fees == sorted(fees, reverse=True))

    page.fill("#q", "urdu")
    page.wait_for_url(re.compile(r"q=urdu"))  # debounced write
    check("search is debounced into the URL", "q=urdu" in page.url)

    filtered_url, filtered_count = page.url, count(page)
    page.reload()
    check("filters survive refresh (URL is the state)",
          page.locator("#location").input_value() == "lahore" and page.get_by_role("checkbox", name="Nutrition & dietetics").is_checked()
          and page.locator("#q").input_value() == "urdu")
    fresh = ctx.browser.new_context().new_page()
    fresh.goto(filtered_url)
    check("shared filtered URL renders the same results in a new session", count(fresh) == filtered_count > 0)
    fresh.context.close()

    page.get_by_role("button", name=re.compile(r"^Reset filters")).click()
    page.wait_for_url(f"{BASE}/professionals")
    check("Reset clears every filter and the URL", count(page) == total and page.locator("#q").input_value() == "")

    page.goto(f"{BASE}/professionals?location=online&visit=in_person")
    check("impossible combination shows the empty state", page.get_by_text("No professionals match these filters").is_visible())
    page.screenshot(path=f"{SHOTS}/w2-02-empty-state.png")
    page.goto(f"{BASE}/professionals?location=atlantis&sort=random&maxFee=-1")
    check("garbage query params are ignored, not crashing", count(page) == total)

    # ---------- Detail pages ----------
    resp = page.goto(f"{BASE}/professionals/ayesha-siddiqui")
    check("direct navigation to a profile URL works (200)", resp.status == 200 and page.locator("h1").inner_text() == "Ayesha Siddiqui")
    check("profile page has a meaningful <title>", "Ayesha Siddiqui" in page.title())
    page.screenshot(path=f"{SHOTS}/w2-03-detail.png", full_page=True)

    resp = page.goto(f"{BASE}/professionals/not-a-real-person")
    check("invalid id returns 404 with not-found UI", resp.status == 404 and page.get_by_text("couldn't find that professional").is_visible())
    resp = page.goto(f"{BASE}/professionals/not-a-real-person/request")
    check("invalid id on the request route also 404s", resp.status == 404)

    # ---------- Favourites ----------
    page.goto(f"{BASE}/professionals/ayesha-siddiqui")
    page.get_by_role("button", name="Save Ayesha Siddiqui").click()
    expect(page.get_by_role("button", name="Remove Ayesha Siddiqui from saved")).to_have_attribute("aria-pressed", "true")
    page.goto(f"{BASE}/saved")
    expect(page.locator(".pro-grid")).to_be_visible()
    check("saved professional appears on /saved after navigation", page.get_by_role("link", name="Ayesha Siddiqui").is_visible())
    page.reload()
    expect(page.locator(".pro-grid")).to_be_visible()
    check("favourites survive refresh", page.get_by_role("link", name="Ayesha Siddiqui").is_visible())
    check("nav shows the saved count", "1 saved" in page.get_by_role("navigation", name="Primary").inner_text())

    # ---------- Multi-step form: validation, a11y, draft persistence ----------
    page.goto(f"{BASE}/professionals/ayesha-siddiqui/request")
    page.get_by_role("button", name="Next").click()
    summary = page.locator(".error-summary")
    expect(summary).to_be_visible()
    check("empty step shows an error summary with role=alert", summary.get_attribute("role") == "alert")
    expect(summary).to_be_focused()
    check("error summary receives focus", page.evaluate("document.activeElement.classList.contains('error-summary')"))
    check("invalid select is aria-invalid and described by its error",
          page.locator("#reason").get_attribute("aria-invalid") == "true"
          and "reason-error" in (page.locator("#reason").get_attribute("aria-describedby") or ""))
    page.screenshot(path=f"{SHOTS}/w2-04-form-errors.png", full_page=True)
    summary.get_by_role("link").first.click()
    check("error link moves focus to the field", page.evaluate("document.activeElement.id") == "visitType-in_person")

    page.get_by_label("Video call").check()
    page.select_option("#reason", "follow_up")
    page.get_by_role("button", name="Next").click()
    expect(page.locator("#day")).to_be_visible()
    check("Next advances once the step is valid", page.locator(".step.current").inner_text().find("Time") >= 0)
    page.select_option("#day", "wed")
    page.get_by_label("14:00").check()

    page.reload()  # the key acceptance check
    expect(page.locator("#day")).to_be_visible()
    check("draft survives refresh (step, day and time restored)",
          page.locator("#day").input_value() == "wed" and page.get_by_label("14:00").is_checked())

    page.get_by_role("button", name="Previous").click()
    check("Previous goes back without losing answers", page.locator("#reason").input_value() == "follow_up")
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Next").click()
    page.fill("#fullName", "Test Person"); page.fill("#email", "not-an-email")
    page.get_by_label("Phone call").check()
    page.get_by_role("button", name="Next").click()
    check("details step validates email and conditional phone",
          page.locator("#email-error").is_visible() and page.locator("#phone-error").is_visible())
    page.fill("#email", "test@example.test"); page.fill("#phone", "+92 300 1234567")
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_text("I understand this is a demo")).to_be_visible()
    page.get_by_role("button", name="Send request").click()
    check("review step requires the acknowledgement", page.locator("#acknowledged-error").is_visible())
    page.get_by_label("I understand this is a demo").check()
    page.get_by_role("button", name="Send request").click()
    expect(page.get_by_text("Request ready (demo)")).to_be_visible()
    page.screenshot(path=f"{SHOTS}/w2-05-form-done.png", full_page=True)
    stored = page.evaluate("localStorage.getItem('hp.appointmentDraft.v1.ayesha-siddiqui')")
    check("draft is cleared after submit", stored is None)

    # ---------- Mobile + accessible nav ----------
    m = browser.new_context(viewport={"width": 375, "height": 800}, is_mobile=True)
    mp = m.new_page()
    mp.goto(f"{BASE}/professionals")
    toggle = mp.get_by_role("button", name="Menu")
    check("mobile: menu collapses behind a button", toggle.is_visible() and not mp.locator("#primary-menu").is_visible())
    toggle.click()
    check("mobile: menu button exposes aria-expanded", toggle.get_attribute("aria-expanded") == "true" and mp.locator("#primary-menu").is_visible())
    mp.keyboard.press("Tab"); mp.keyboard.press("Escape")
    check("mobile: Escape closes the menu", toggle.get_attribute("aria-expanded") == "false")
    check("mobile: no horizontal scroll", mp.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    mp.screenshot(path=f"{SHOTS}/w2-06-mobile.png", full_page=True)
    mp.goto(f"{BASE}/professionals/sana-malik/request")
    check("mobile: form has no horizontal scroll", mp.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

    check("no uncaught JS errors", not errors or print(errors))
    browser.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
