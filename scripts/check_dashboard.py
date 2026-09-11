"""Browser smoke test against a running local API; creates mock fixture runs."""

import argparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        mutations = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: mutations.append(request.url) if request.method == "POST" else None)
        page.goto(args.url)
        page.wait_for_function("document.querySelector('#qwen-id').textContent.length > 0")
        expect(page.locator("#tutorial-welcome")).to_be_visible()
        page.locator("#start-tour").click()
        expect(page.locator("#tutorial-title")).to_be_focused()
        expect(page.locator("#tutorial-back")).to_be_disabled()
        # Escape, focus restoration and dismissal survive reload. Help is optional.
        page.keyboard.press("Escape")
        expect(page.locator("#tutorial-dialog")).not_to_be_visible()
        expect(page.locator("#help-tour")).to_be_focused()
        page.reload()
        expect(page.locator("#tutorial-welcome")).not_to_be_visible()
        page.locator("#help-tour").click()
        expect(page.locator("#tutorial-progress")).to_have_text("STEP 1 OF 6")
        # Every lesson fits narrow screens and keyboard focus stays in the modal.
        page.set_viewport_size({"width": 390, "height": 844})
        for lesson in range(1, 7):
            expect(page.locator("#tutorial-progress")).to_have_text(f"STEP {lesson} OF 6")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.locator("#tutorial-dialog").evaluate("el => el.scrollWidth <= el.clientWidth")
            page.keyboard.press("Tab")
            assert page.evaluate("document.querySelector('#tutorial-dialog').contains(document.activeElement)")
            page.locator("#tutorial-next").click()
        expect(page.locator("#tutorial-dialog")).not_to_be_visible()
        assert not mutations, "Reading the tutorial must not create or approve runs"
        # Tour links open the normal form; synthetic-data confirmation is still required.
        page.locator("#help-tour").click()
        page.locator('[data-lesson="1"]').click()
        page.locator("#tutorial-show").click()
        expect(page.locator("#run-dialog")).to_be_visible()
        expect(page.locator("#synthetic-confirm")).not_to_be_checked()
        assert not mutations
        page.locator("#provider").select_option("mock")
        page.locator("#synthetic-confirm").check()
        page.locator("#start-run").click()
        page.locator("#mapping-panel").wait_for(state="visible")
        assert page.locator("#confirm").is_disabled()
        expect(page.locator("#next-step-title")).to_contain_text("Review the mapping")
        mapping = page.locator('#mapping-tables select[data-kind="servicing"][data-raw="ScheduledInstalment"]')
        previous_mapping = mapping.input_value()
        mapping.select_option("")
        post_count = len(mutations)
        page.locator('[data-tutorial="2"]').click()
        expect(page.locator("#tutorial-progress")).to_have_text("STEP 3 OF 6")
        page.locator("#tutorial-back").click()
        expect(page.locator("#tutorial-progress")).to_have_text("STEP 2 OF 6")
        page.locator("#tutorial-next").click()
        page.locator("#tutorial-show").click()
        expect(mapping).to_have_value("")
        expect(page.locator("#mapping-reviewed")).not_to_be_checked()
        expect(page.locator("#confirm")).to_be_disabled()
        assert len(mutations) == post_count, "Mapping help must preserve edits and require real confirmation"
        mapping.select_option(previous_mapping)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator(".mapping-grid .samples").first.is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.locator("#mapping-reviewed").check()
        page.locator("#confirm").click()
        page.wait_for_function("document.querySelector('#status-badge').textContent === 'Run complete'")
        assert page.locator("#metric-found").inner_text() == "12"
        assert page.locator("#metric-pass").inner_text() == "12"
        expect(page.locator("#next-step-title")).to_contain_text("Open a finding")
        page.locator('[data-tutorial="3"]').click()
        expect(page.locator("#tutorial-progress")).to_have_text("STEP 4 OF 6")
        expect(page.locator("#tutorial-visual")).to_contain_text("does not mean the loan is problem-free")
        page.locator("#tutorial-show").click()
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
    print("Dashboard smoke passed: tutorial navigation, dismissal/replay, keyboard focus, no automatic approvals, mapping edits retained, checkpoint, results, evidence, search, activity, connections and mobile layout")


if __name__ == "__main__":
    main()
