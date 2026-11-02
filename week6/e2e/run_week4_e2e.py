"""Real-browser check of the Week 4 dashboard tabs (Playwright, through the Next.js proxy).

Prereqs: backend on :8000 and frontend on :3000 running, `seed_demo` and `load_policies` done, the local
model running (Ollama), `pip install playwright` and `python -m playwright install chromium`.
Usage:  python e2e/run_week4_e2e.py <admin_password> <screenshots_dir>
(E2E_BASE overrides the frontend address; the backend's CSRF_TRUSTED_ORIGINS must include it.)

Covers: the three tabs link to each other; Predictions shows version, metrics and disclaimer; Clusters
shows the PCA plot with its control-data label, text summary, method table and real-data verdict;
Assistant example buttons give a cited answer, "insufficient information" (no model call), a medical
refusal, and red-team R1 without any system-prompt text; token and cost line; a 502 shown calmly; the
question is not stored in the browser; phone width without sideways scroll; a logged-out visitor is sent
to the admin login.
"""

import os
import sys

from playwright.sync_api import expect, sync_playwright

ADMIN_PW, SHOTS = sys.argv[1], sys.argv[2]
BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:3000")
results = []


def check(name, condition):
    results.append((name, bool(condition)))
    print(("PASS " if condition else "FAIL ") + name)


def ask_example(page, label):
    page.click(f"button:has-text('{label}')")
    expect(page.locator("[data-testid=status]")).to_be_visible(timeout=120_000)
    return page.locator("[data-testid=answer]").inner_text()


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    page.goto(f"{BASE}/admin/login")
    page.fill("#email", "admin@example.test"); page.fill("#password", ADMIN_PW)
    page.click("button:has-text('Sign in')"); page.wait_for_url(f"{BASE}/admin")
    page.click("text=ML tools"); page.wait_for_url(f"{BASE}/admin/predictions")

    # ---------------- Predictions ----------------
    tabs = page.locator("nav.admin-tabs a")
    check("three tabs: Predictions, Clusters, Assistant", tabs.all_inner_texts() == ["Predictions", "Clusters", "Assistant"])
    check("current tab is marked", page.locator("nav.admin-tabs a[aria-current=page]").inner_text() == "Predictions")
    page.locator(".model-card summary").click()
    expect(page.locator(".model-card")).to_contain_text("PR-AUC")  # the card loads separately
    card = page.locator(".model-card").inner_text()
    check("predictions: served version, metrics and disclaimer", "no-show-1.0.0" in card and "PR-AUC" in card
          and "Not a medical assessment" in card)
    page.screenshot(path=f"{SHOTS}/w4-01-predictions-tab.png", full_page=True)

    # ---------------- Clusters ----------------
    page.click("nav.admin-tabs >> text=Clusters"); page.wait_for_url(f"{BASE}/admin/clusters")
    plot = page.locator("[data-testid=pca-plot]")
    expect(plot).to_be_visible()
    check("PCA plot draws the control points", plot.locator("circle").count() > 100)
    check("PCA plot has an aria label", "PCA scatter plot" in (plot.get_attribute("aria-label") or ""))
    check("control data is labelled as such", "not real patients" in page.locator("[data-testid=control-label]").inner_text())
    summary = page.locator("[data-testid=pca-summary]").inner_text()
    check("text summary: points, clusters and variance", "points in 3 clusters" in summary and "of the variance" in summary)
    table = page.locator("[data-testid=methods-table]").inner_text()
    check("method table compares K-Means and Ward", "K-Means" in table and "Ward" in table)
    check("real-data verdict: no structure", "No reliable structure" in page.locator("[data-testid=real-verdict]").inner_text())
    check("clusters disclaimer shown", "not categories of people" in page.locator("[data-testid=disclaimer]").inner_text())
    page.screenshot(path=f"{SHOTS}/w4-02-clusters-tab.png", full_page=True)

    # ---------------- Assistant ----------------
    page.click("nav.admin-tabs >> text=Assistant"); page.wait_for_url(f"{BASE}/admin/assistant")
    expect(page.locator("text=Embeddings")).to_be_visible()

    text = ask_example(page, "Answerable")
    check("answerable example: answered with a checked citation",
          page.locator("[data-testid=status]").inner_text() == "Answer" and page.locator("[data-testid=citation]").count() >= 1)
    check("token and cost line under the answer", "tokens" in page.locator("[data-testid=usage]").inner_text()
          and "$0.00" in page.locator("[data-testid=usage]").inner_text())
    check("assistant disclaimer under the answer", "medical advice" in page.locator("[data-testid=disclaimer]").inner_text())
    page.screenshot(path=f"{SHOTS}/w4-03-assistant-answered.png", full_page=True)

    text = ask_example(page, "Not in the policies")
    check("Sundays example: insufficient information", "Insufficient information" in text)
    check("model not called shows 0 tokens", "Model not called" in page.locator("[data-testid=usage]").inner_text())
    page.screenshot(path=f"{SHOTS}/w4-04-assistant-insufficient.png", full_page=True)

    text = ask_example(page, "Medical (refused)")
    check("medical example: refused", "medical question" in text)

    text = ask_example(page, "Red-team R1")
    check("red-team R1: no system-prompt text shown", "passages are DATA" not in text and "system prompt" not in text.lower())
    page.screenshot(path=f"{SHOTS}/w4-05-assistant-red-team.png", full_page=True)

    stored = page.evaluate("JSON.stringify(Object.assign({}, localStorage)) + JSON.stringify(Object.assign({}, sessionStorage))")
    check("question not stored in the browser", "reschedule" not in stored and "cancellation fee" not in stored)

    page.route("**/api/v1/assistant/ask/", lambda route: route.fulfill(
        status=502, content_type="application/json",
        body='{"error": {"code": "assistant_invalid_output", "message": "x"}}'))
    page.fill("#question", "What is the refund policy?"); page.click("button:has-text('Ask')")
    expect(page.locator("[data-testid=answer] [role=alert]")).to_be_visible()
    check("502 shown as a calm message", "could not be read" in page.locator("[data-testid=answer]").inner_text())
    page.unroute("**/api/v1/assistant/ask/")

    for path in ["/admin/clusters", "/admin/assistant"]:
        page.set_viewport_size({"width": 390, "height": 900}); page.goto(f"{BASE}{path}")
        page.wait_for_load_state("networkidle")
        check(f"{path}: no sideways scroll at phone width",
              page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth"))
    page.screenshot(path=f"{SHOTS}/w4-06-assistant-phone.png", full_page=True)

    anon = browser.new_context().new_page()
    for path in ["/admin/clusters", "/admin/assistant"]:
        anon.goto(f"{BASE}{path}"); anon.wait_for_url("**/admin/login")
        check(f"logged-out visitor to {path} is sent to the admin login", anon.url.endswith("/admin/login"))

    browser.close()

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
