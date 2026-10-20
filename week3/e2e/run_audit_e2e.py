"""Real-browser checks for the Week 2 (AI/ML track) additions: profile completion and audit events.

Prereqs: backend on :8000 and frontend on :3000 running, `seed_demo` already run, `pip install playwright`.
Usage:  python e2e/run_audit_e2e.py <admin_password> <screenshots_dir>
Re-runnable: each run signs up a fresh, uniquely named member.
"""
import sys, time
from playwright.sync_api import sync_playwright, expect

ADMIN_PW, SHOTS = sys.argv[1], sys.argv[2]
BASE = "http://127.0.0.1:3000"
EMAIL = f"audit{int(time.time())}@example.test"
PW = "Correct-Horse-9-Battery"
SECRET_PHONE = "+1 555 010 0177"
results = []

def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)

with sync_playwright() as p:
    browser = p.chromium.launch()

    # ---------- member: completion goes from 0% to 100% ----------
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    page = ctx.new_page()
    page.goto(f"{BASE}/signup")
    page.fill("#name", "Audit Tester"); page.fill("#email", EMAIL); page.fill("#password", PW)
    page.click("button:has-text('Create account')"); page.wait_for_url("**/profile")
    bar = page.get_by_role("progressbar", name="Profile completion")
    expect(bar).to_have_attribute("aria-valuenow", "0")
    check("new member sees 0% completion and the missing sections",
          "Emergency contact (name, relationship and phone)" in page.content())

    page.select_option("#agemode", "range"); page.select_option("#range", "25-34")
    page.fill("#goals", "Walk more")
    page.click("button:has-text('Save profile')"); expect(page.locator(".alert.ok")).to_be_visible()
    expect(bar).to_have_attribute("aria-valuenow", "67")
    check("partial profile shows 67% (emergency contact still missing)", True)

    page.fill("#ecn", "Pat Tester"); page.fill("#ecr", "Sibling"); page.fill("#ecp", SECRET_PHONE)
    page.click("button:has-text('Save profile')"); expect(page.locator(".alert.ok")).to_be_visible()
    expect(bar).to_have_attribute("aria-valuenow", "100")
    check("complete profile shows 100% and a 'complete' badge", "Still to fill in" not in page.content())
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(700)  # let the progress bar finish its fill animation
    page.screenshot(path=f"{SHOTS}/w2-07-profile-completion.png")

    # ---------- admin: completion filter and audit trail ----------
    a = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()
    a.goto(f"{BASE}/admin/login")
    a.fill("#email", "admin@example.test"); a.fill("#password", ADMIN_PW); a.click("button:has-text('Sign in')")
    a.wait_for_url("**/admin"); expect(a.locator("table tbody tr").first).to_be_visible()

    a.select_option("[aria-label='Completion']", "incomplete")
    expect(a.locator("table tbody tr", has_text="Carlos Mendez")).to_have_count(1)
    check("admin 'Incomplete' filter shows the seeded incomplete profile", True)
    a.fill("[aria-label='Search name or email']", EMAIL)
    expect(a.locator("table tbody tr td.muted")).to_have_text("No profiles match.")
    check("completed member is excluded from the 'Incomplete' filter", True)
    a.select_option("[aria-label='Completion']", "complete")
    expect(a.locator("table tbody tr")).to_have_count(1)
    check("...and included in the 'Complete' filter", EMAIL in a.content())

    a.click("a:has-text('View')"); expect(a.locator("h1")).to_have_text("Audit Tester")
    activity = a.locator(".card", has=a.locator("h2", has_text="Activity"))
    expect(activity.locator("tbody tr").first).to_be_visible()
    text = activity.inner_text()
    check("trail lists profile created, updated and this admin's view",
          all(s in text for s in ["Profile created", "Profile updated", "Admin viewed profile"]))
    check("trail shows changed field names", "emergency_contact_phone" in text and "wellness_goals" in text)
    check("trail never shows field values", SECRET_PHONE not in text)

    a.once("dialog", lambda d: d.accept())
    a.click("button:has-text('Deactivate profile')")
    expect(activity.locator("tbody tr", has_text="Admin deactivated profile")).to_have_count(1)
    check("deactivation appears in the trail straight away", True)
    a.evaluate("window.scrollTo(0, 0)")
    a.screenshot(path=f"{SHOTS}/w2-08-admin-audit-trail.png", full_page=True)
    a.click("button:has-text('Reactivate profile')")
    expect(activity.locator("tbody tr", has_text="Admin reactivated profile")).to_have_count(1)

    r = page.request.get(f"{BASE}/api/admin/audit-events/")
    check("member cannot read the audit log (401)", r.status == 401)
    browser.close()

passed = sum(ok for _, ok in results)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
