"""Browser smoke test against a running local API; creates mock fixture runs."""

from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8765/")
        page.wait_for_function("document.querySelector('#qwen-id').textContent.length > 0")
        page.locator("#new-run").click()
        page.locator("#provider").select_option("mock")
        page.locator("#synthetic-confirm").check()
        page.locator("#start-run").click()
        page.locator("#mapping-panel").wait_for(state="visible")
        assert page.locator("#confirm").is_disabled()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator(".mapping-grid .samples").first.is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.locator("#mapping-reviewed").check()
        page.locator("#confirm").click()
        page.wait_for_function("document.querySelector('#status-badge').textContent === 'Run complete'")
        assert page.locator("#metric-found").inner_text() == "12"
        assert page.locator("#metric-pass").inner_text() == "12"
        page.locator(".evidence-button").first.click()
        assert page.get_by_text("Verbatim source records", exact=True).is_visible()
        assert page.get_by_text("AI explanation · passed configured checks", exact=True).is_visible()
        page.locator("#close-evidence").click()
        page.locator("#search").fill("SYN-L000013")
        assert page.locator(".exception-row").count() == 1
        page.locator("[data-view=audit]").first.click()
        assert page.locator(".timeline-row").count() > 27
        page.locator("[data-view=settings]").first.click()
        assert page.locator("#qwen-id").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
        browser.close()
    print("Dashboard smoke passed: checkpoint, results, evidence, search, activity, connections and mobile layout")


if __name__ == "__main__":
    main()
