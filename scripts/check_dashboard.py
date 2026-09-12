"""Browser acceptance checks for the consumer payment overview and CSV uploads."""

import argparse
import json
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def confirm_labels(page, mapping=None):
    page.locator("#mapping-panel").wait_for(state="visible")
    expect(page.locator("#confirm")).to_be_disabled()
    if mapping:
        for kind, columns in mapping.items():
            for raw, field in columns.items():
                page.get_by_label(f"{kind} {raw} mapping", exact=True).select_option(field)
    page.locator("#mapping-reviewed").check()
    page.locator("#confirm").click()
    expect(page.locator("#status-badge")).to_have_text("Check complete", timeout=15000)


def amount(value):
    from decimal import Decimal
    return f"£{Decimal(value):,.2f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    with sync_playwright() as playwright, tempfile.TemporaryDirectory() as downloads:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width":1440,"height":1000})
        errors, mutations = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: mutations.append(request.url) if request.method == "POST" else None)
        page.goto(args.url)
        page.locator("#currency-select").select_option("GBP")
        expect(page.locator("#example-cards .example-card")).to_have_count(6)
        expect(page.locator("#tutorial-welcome")).to_be_visible()
        page.locator("#start-tour").click()
        expect(page.locator("#tutorial-title")).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("#help-tour")).to_be_focused()
        page.reload()
        expect(page.locator("#tutorial-welcome")).not_to_be_visible()
        page.locator("#help-tour").click()
        page.set_viewport_size({"width":390,"height":844})
        for lesson in range(1,7):
            expect(page.locator("#tutorial-progress")).to_have_text(f"STEP {lesson} OF 6")
            assert page.locator("#tutorial-dialog").evaluate("el => el.scrollWidth <= el.clientWidth")
            page.keyboard.press("Tab")
            assert page.evaluate("document.querySelector('#tutorial-dialog').contains(document.activeElement)")
            page.locator("#tutorial-next").click()
        assert not mutations, "Reading help must not create or approve a check"
        page.locator("#new-run").click()
        page.locator(".run-options").evaluate("el => el.open = true")
        page.locator("#provider").select_option("mock")
        expect(page.locator("#synthetic-confirm")).not_to_be_checked()
        page.locator("#synthetic-confirm").check()
        page.locator("#start-run").click()
        page.locator("#mapping-panel").wait_for(state="visible")
        expect(page.locator("#metric-due")).to_have_text("—")
        target = page.get_by_label("servicing ScheduledInstalment mapping", exact=True)
        target.select_option("")
        before_help = len(mutations)
        page.locator('[data-tutorial="2"]').click()
        page.locator("#tutorial-show").click()
        expect(target).to_have_value("")
        expect(page.locator("#confirm")).to_be_disabled()
        assert len(mutations) == before_help
        target.select_option("scheduled_amount")
        confirm_labels(page)
        expect(page.locator("#metric-due")).to_have_text("£66,561.34")
        expect(page.locator("#metric-paid")).to_have_text("£67,053.18")
        expect(page.locator("#metric-shortfall")).to_have_text("£7,430.01")
        expect(page.locator("#chart-excess")).to_have_text("£7,921.85")
        expect(page.locator("#metric-accounts")).to_have_text("12")
        expect(page.locator(".exception-row")).to_have_count(12)
        # Currency is a remembered display label, never a conversion or new check.
        before_currency = len(mutations)
        for currency, symbol in [("EUR", "€"), ("USD", "$"), ("GBP", "£")]:
            page.locator("#currency-select").select_option(currency)
            expect(page.locator("#metric-due")).to_have_text(symbol + "66,561.34")
            expect(page.locator("#payment-bars")).to_contain_text(symbol + "67,053.18")
            expect(page.locator("#currency-note")).to_contain_text(currency)
        assert len(mutations) == before_currency
        page.reload()
        expect(page.locator("#currency-select")).to_have_value("GBP")
        expect(page.locator("#metric-paid")).to_have_text("£67,053.18")
        page.locator("#open-chat").click()
        page.get_by_role("button", name="Why is there a shortfall?", exact=True).click()
        expect(page.locator("#chat-messages .assistant")).to_contain_text("£7,430.01")
        page.get_by_text("Supporting CSV records", exact=True).click()
        expect(page.locator("#chat-messages")).to_contain_text("servicing_extract.csv")
        page.locator("#chat-question").fill("Should I refinance?")
        page.locator("#chat-send").click()
        expect(page.locator("#chat-messages .assistant").last).to_contain_text("cannot recommend a mortgage")
        page.keyboard.press("Escape")
        expect(page.locator("#open-chat")).to_be_focused()
        assert all(url.endswith("/chat") for url in mutations[before_currency:])
        page.locator("#account-select").select_option("SYN-L000005")
        expect(page.locator("#metric-due")).to_have_text("£2,580.61")
        expect(page.locator("#metric-paid")).to_have_text("£0.00")
        expect(page.locator("#donut-total")).to_have_text("1")
        page.locator("#open-chat").click()
        expect(page.locator("#chat-messages")).to_be_empty()
        expect(page.locator("#chat-context")).to_contain_text("SYN-L000005")
        page.get_by_role("button", name="What's on this screen?", exact=True).click()
        expect(page.locator("#chat-messages .assistant")).to_contain_text("£2,580.61")
        expect(page.locator("#chat-messages .assistant")).not_to_contain_text("£66,561.34")
        assert page.locator("#chat-dialog").evaluate("el => el.scrollWidth <= el.clientWidth")
        page.locator("#close-chat").click()
        page.locator(".evidence-button").first.click()
        expect(page.locator("#evidence-content")).to_contain_text("No payment row exists")
        expect(page.locator(".source-fields")).to_have_count(2)
        expect(page.locator(".detail-facts")).to_contain_text("£2,580.61")
        expect(page.locator("#evidence-content pre").first).not_to_be_visible()
        page.locator("#close-evidence").click()
        page.locator("#account-select").select_option("")
        page.locator('[data-queue="rates"]').click()
        expect(page.locator(".exception-row")).to_have_count(4)
        page.locator(".evidence-button").first.click()
        expect(page.locator("#evidence-content")).to_contain_text("not the full interest rate or APR")
        page.locator("#close-evidence").click()
        page.locator('[data-queue="all"]').click()
        # Both handoffs are real UI actions: use an example, and upload downloaded CSVs.
        page.locator('[data-view="examples"]').click()
        page.locator('[data-example="mixed_checks"]').click()
        expect(page.locator("#example-select")).to_have_value("mixed_checks")
        expect(page.locator("#synthetic-confirm")).not_to_be_checked()
        page.locator(".run-options").evaluate("el => el.open = true")
        page.locator("#provider").select_option("mock")
        page.locator("#synthetic-confirm").check()
        page.locator("#start-run").click()
        confirm_labels(page)
        expect(page.locator("#metric-accounts")).to_have_text("3")
        expect(page.locator(".exception-row")).to_have_count(5)
        # Each downloaded pack is unzipped and fed through the file inputs.
        catalog = json.loads((ROOT / "data/scenarios/catalog.json").read_text())
        for entry in catalog:
            import zipfile
            page.locator('[data-view="examples"]').click()
            with page.expect_download() as download:
                page.locator(f'a[href="/examples/{entry["id"]}/download"]').click()
            archive_path = Path(downloads) / f'{entry["id"]}.zip'
            download.value.save_as(archive_path)
            folder = Path(downloads) / entry["id"]
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(folder)
            expected = json.loads((folder / "expected.json").read_text())
            mapping = json.loads((folder / "mapping.json").read_text())
            page.locator("#new-run").click()
            page.locator('[name="source"][value="upload"]').check()
            # An incomplete upload is caught in the form without closing it.
            if entry["id"] == "all_clear":
                before_invalid = len(mutations)
                page.locator("#synthetic-confirm").check()
                page.locator("#start-run").click()
                expect(page.locator("#run-form-error")).to_contain_text("Add all three CSV files")
                expect(page.locator("#run-dialog")).to_be_visible()
                assert len(mutations) == before_invalid
            for kind, filename in entry["files"].items():
                page.locator("#upload-" + kind).set_input_files(str(folder / filename))
            page.locator(".run-options").evaluate("el => el.open = true")
            page.locator("#provider").select_option("mock")
            page.locator("#synthetic-confirm").check()
            page.locator("#start-run").click()
            confirm_labels(page,mapping)
            expect(page.locator("#metric-due")).to_have_text(amount(expected["totals"]["scheduled"]))
            expect(page.locator("#metric-paid")).to_have_text(amount(expected["totals"]["received"]))
            expect(page.locator("#metric-shortfall")).to_have_text(amount(expected["totals"]["shortfall"]))
            expect(page.locator("#chart-excess")).to_have_text(amount(expected["totals"]["excess"]))
            expect(page.locator("#metric-accounts")).to_have_text(str(expected["affected_account_count"]))
            expect(page.locator("#donut-total")).to_have_text(str(expected["account_count"]))
            expect(page.locator(".exception-row")).to_have_count(len(expected["findings"]))
            assert page.locator("#payment-donut").get_attribute("aria-label")
            page.locator('[data-view="audit"]').click()
            expect(page.locator("#ground-truth")).to_contain_text("Not scored here")
            assert page.locator(".timeline-row").count() > 5
            page.locator('[data-view="desk"]').click()
        for width in [320,390,768,1024,1440]:
            page.set_viewport_size({"width":width,"height":900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
        page.locator('[data-view="settings"]').click()
        expect(page.locator("#qwen-id")).to_be_visible()
        assert not errors, errors
        browser.close()
    print("PASS: consumer metrics, account filter, plain-language details, tutorial, human confirmation, example handoff, six ZIP downloads and CSV uploads, independent expected results, mobile layouts; no browser errors")


if __name__ == "__main__":
    main()
