"""Real-browser E2E (Playwright) through the Next.js proxy, covering both roles.

Prereqs: backend on :8000 and frontend on :3000 running, `seed_demo` already run, `pip install playwright`.
Usage:  python e2e/run_e2e.py <admin_password> <screenshots_dir>

Rate limiting: one run makes ~8 login/refresh calls and the API allows 10/min per IP by default
(that limit is a feature, and is unit-tested). A single run passes with defaults; to run the script
repeatedly, start the BACKEND with `THROTTLE_LOGIN=1000/min`, or wait 60 s between runs.
Re-runnable: each run signs up a fresh, uniquely named member.
"""
import json, sys, time
from playwright.sync_api import sync_playwright, expect

ADMIN_PW, SHOTS = sys.argv[1], sys.argv[2]
BASE = "http://127.0.0.1:3000"
EMAIL = f"e2e{int(time.time())}@example.test"
PW = "Correct-Horse-9-Battery"
results = []

def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)

with sync_playwright() as p:
    browser = p.chromium.launch()
    # ---------- Role 1: member ----------
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    page = ctx.new_page()
    page.goto(f"{BASE}/"); page.screenshot(path=f"{SHOTS}/01-home.png")

    page.goto(f"{BASE}/signup")
    page.fill("#name", "E2E Tester"); page.fill("#email", EMAIL); page.fill("#password", "short")
    page.click("button:has-text('Create account')")
    expect(page.locator(".field-error").first).to_be_visible()
    check("signup shows server-side password validation", "password" in page.content().lower())
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=f"{SHOTS}/02-signup-validation.png")

    page.fill("#password", PW); page.click("button:has-text('Create account')")
    page.wait_for_url("**/profile")
    check("signup logs in and lands on /profile", page.url.endswith("/profile"))
    expect(page.locator("#full_name")).to_have_value("E2E Tester")

    cookies = {c["name"]: c for c in ctx.cookies()}
    check("access+refresh cookies are HttpOnly", cookies["hp_access"]["httpOnly"] and cookies["hp_refresh"]["httpOnly"])
    check("JS cannot read the JWT (document.cookie)", "hp_access" not in page.evaluate("document.cookie"))
    check("no token in localStorage/sessionStorage", page.evaluate("localStorage.length + sessionStorage.length") == 0)

    page.fill("#goals", "Walk more\nSleep 8 hours"); page.fill("#allergies", "Pollen")
    page.select_option("#contact", "sms"); page.fill("#dob", "1992-04-09")
    page.fill("#ecn", "Pat Tester"); page.fill("#ecr", "Sibling"); page.fill("#ecp", "+1 555 010 0188")
    page.click("button:has-text('Save profile')")
    expect(page.locator(".alert.ok")).to_be_visible()
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=f"{SHOTS}/03-profile-saved.png", full_page=True)
    page.reload(); expect(page.locator("#goals")).to_have_value("Walk more\nSleep 8 hours")
    check("profile edits persist across reload", True)

    page.fill("#ecp", "call me maybe"); page.click("button:has-text('Save profile')")
    expect(page.locator(".field-error")).to_be_visible()
    check("invalid phone rejected with field error", True)

    # user JWT must not unlock the admin area
    r = page.request.get(f"{BASE}/api/admin/profiles/")
    check("member JWT -> /api/admin/profiles/ is 401", r.status == 401)
    page.goto(f"{BASE}/admin"); page.wait_for_url("**/admin/login")
    check("member visiting /admin is bounced to admin login", True)

    # silent refresh: drop the access cookie (as if it expired); app should recover via refresh cookie
    ctx.clear_cookies(name="hp_access")
    page.goto(f"{BASE}/profile"); expect(page.locator("#full_name")).to_be_visible()
    check("expired access cookie is silently refreshed", True)

    page.click("button:has-text('Sign out')"); page.wait_for_url("**/login")
    page.goto(f"{BASE}/profile"); page.wait_for_url("**/login")
    check("after sign-out /profile redirects to login", True)

    # ---------- Role 2: admin ----------
    actx = browser.new_context(viewport={"width": 1100, "height": 900})
    a = actx.new_page()
    a.goto(f"{BASE}/admin"); a.wait_for_url("**/admin/login")
    check("anonymous /admin redirects to admin login", True)

    a.fill("#email", "admin@example.test"); a.fill("#password", "wrong-password-here")
    a.click("button:has-text('Sign in')"); expect(a.locator(".alert.error")).to_be_visible()
    check("wrong admin password shows generic error", "Invalid email or password" in a.content())

    a.fill("#email", EMAIL); a.fill("#password", PW); a.click("button:has-text('Sign in')")
    expect(a.locator(".alert.error")).to_be_visible()
    check("member credentials rejected on admin login", a.url.endswith("/admin/login"))

    a.fill("#email", "admin@example.test"); a.fill("#password", ADMIN_PW); a.click("button:has-text('Sign in')")
    a.wait_for_url("**/admin"); expect(a.locator("table tbody tr").first).to_be_visible()
    acookies = {c["name"]: c for c in actx.cookies()}
    check("admin gets HttpOnly session cookie, no JWT", acookies["hp_admin_session"]["httpOnly"] and "hp_access" not in acookies)
    a.evaluate("window.scrollTo(0, 0)")
    a.screenshot(path=f"{SHOTS}/04-admin-dashboard.png")

    # forging client state does nothing
    a.evaluate("localStorage.setItem('role','admin'); document.cookie='is_admin=true'")
    actx.clear_cookies(name="hp_admin_session")
    a.goto(f"{BASE}/admin"); a.wait_for_url("**/admin/login")
    check("faked localStorage/cookie 'admin' state grants nothing", True)
    a.fill("#email", "admin@example.test"); a.fill("#password", ADMIN_PW); a.click("button:has-text('Sign in')")
    a.wait_for_url("**/admin")

    # Search by the unique email: earlier runs leave other "E2E Tester" members behind, so a name
    # search would (correctly) return several rows and make this script non re-runnable.
    a.fill("[aria-label='Search name or email']", EMAIL)
    expect(a.locator("table tbody tr")).to_have_count(1)
    check("admin search finds the new member", EMAIL in a.content())
    a.select_option("[aria-label='Status']", "active")
    a.fill("[aria-label='Search name or email']", "")
    a.wait_for_timeout(700)
    check("pagination shown for >10 rows", "Page 1 of" in a.content())

    a.fill("[aria-label='Search name or email']", EMAIL)
    expect(a.locator("table tbody tr")).to_have_count(1)
    a.click("a:has-text('View')"); expect(a.locator("h1")).to_have_text("E2E Tester")
    check("detail shows emergency contact + goals", "Pat Tester" in a.content() and "Walk more" in a.content())
    a.evaluate("window.scrollTo(0, 0)")
    a.screenshot(path=f"{SHOTS}/05-admin-detail.png", full_page=True)

    a.once("dialog", lambda d: d.accept())
    a.click("button:has-text('Deactivate profile')")
    expect(a.locator(".badge.off").first).to_be_visible()
    check("admin deactivated the member", True)

    # deactivated member cannot sign in
    page.goto(f"{BASE}/login"); page.fill("#email", EMAIL); page.fill("#password", PW)
    page.click("button:has-text('Sign in')"); expect(page.locator(".alert.error")).to_be_visible()
    check("deactivated member cannot log in", page.url.endswith("/login"))

    a.click("button:has-text('Reactivate profile')"); expect(a.locator(".badge.off")).to_have_count(0)
    page.click("button:has-text('Sign in')"); page.wait_for_url("**/profile")
    check("reactivated member can log in again", True)

    a.goto(f"{BASE}/admin"); a.click("button:has-text('Sign out')"); a.wait_for_url("**/admin/login")
    r = actx.request.get(f"{BASE}/api/admin/profiles/")
    check("admin logout invalidates session server-side", r.status == 401)

    # mobile layout
    m = browser.new_context(viewport={"width": 375, "height": 740}).new_page()
    m.goto(f"{BASE}/login"); m.screenshot(path=f"{SHOTS}/06-mobile-login.png")
    check("no horizontal scroll on mobile", m.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    browser.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
