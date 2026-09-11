import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


PACK = Path(__file__).resolve().parents[1] / "data" / "scenarios" / "all_clear"


class PaymentSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = TestClient(create_app(storage=Path(self.temp.name) / "runs", environ={}))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.mapping = json.loads((PACK / "mapping.json").read_text())
        self.files = {kind: (PACK / name).read_text() for kind, name in {
            "servicing": "servicing_extract.csv", "payments": "payments_file.csv", "investor": "investor_report.csv"}.items()}

    def finish(self):
        paused = self.client.post("/runs", json={"files": self.files}).json()
        self.assertIsNone(paused["payment_summary"])
        return self.client.post(f"/runs/{paused['run_id']}/confirm", json={"mapping": self.mapping}).json()

    def test_incomplete_mapping_never_publishes_zero_or_partial_payment_totals(self):
        self.mapping["payments"] = {raw: field for raw, field in self.mapping["payments"].items() if field != "received_amount"}
        done = self.finish()
        self.assertEqual(done["status"], "complete")
        self.assertFalse(done["payment_summary"]["available"])
        self.assertNotIn("received", done["payment_summary"])
        self.assertEqual(done["payment_summary"]["accounts"], [])

    def test_missing_lender_row_is_unknown_not_zero_or_full_rate_coverage(self):
        self.files["investor"] = "\n".join(self.files["investor"].splitlines()[:-1]) + "\n"
        done = self.finish()
        self.assertEqual(done["status"], "complete")
        summary = done["payment_summary"]
        self.assertEqual(summary["account_count"], 4)
        self.assertEqual(summary["margin_checked_accounts"], 3)
        self.assertIsNone(summary["reported"])
        self.assertIsNone(summary["accounts"][-1]["reported"])
        self.assertIsNone(summary["accounts"][-1]["charged_margin"])
        self.assertEqual(summary["received"], "3050.50")

    def test_catalog_downloads_are_the_same_csv_bytes_as_upload_examples(self):
        catalog = self.client.get("/examples").json()
        self.assertEqual(len(catalog), 6)
        for entry in catalog:
            with self.subTest(pack=entry["id"]):
                example = self.client.get("/examples/" + entry["id"]).json()
                self.assertEqual(set(example["files"]), {"servicing", "payments", "investor"})
                self.assertNotIn("expected", example)
                response = self.client.get("/examples/" + entry["id"] + "/download")
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    for kind, filename in entry["files"].items():
                        self.assertEqual(archive.read(filename).decode(), example["files"][kind])
        self.assertEqual(self.client.get("/examples/no-such-pack").status_code, 404)
        self.assertEqual(self.client.get("/examples/%2E%2E%2F%2E%2E/download").status_code, 404)


if __name__ == "__main__":
    unittest.main()
