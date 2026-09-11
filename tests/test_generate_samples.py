"""Verify fixture reproducibility and the answer key against the raw CSVs."""

import csv
import json
import random
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from data.generate_samples import generate_samples


ROOT = Path(__file__).resolve().parents[1]
FILENAMES = (
    "servicing_extract.csv", "payments_file.csv", "investor_report.csv", "ground_truth.json",
)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class SampleGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_seed_42_is_byte_identical_across_runs_and_matches_checked_in_samples(self):
        first, second = self.directory / "first", self.directory / "second"
        generate_samples(first, seed=42, n_loans=40)
        generate_samples(second, seed=42, n_loans=40)
        for filename in FILENAMES:
            with self.subTest(filename=filename):
                expected = (first / filename).read_bytes()
                self.assertEqual(expected, (second / filename).read_bytes())
                self.assertEqual(expected, (ROOT / "data/samples" / filename).read_bytes())

    def test_different_seed_changes_loan_values_and_affected_loans(self):
        first, second = self.directory / "first", self.directory / "second"
        a = generate_samples(first, seed=42, n_loans=40)
        b = generate_samples(second, seed=43, n_loans=40)
        self.assertNotEqual(
            (first / "servicing_extract.csv").read_bytes(),
            (second / "servicing_extract.csv").read_bytes(),
        )
        self.assertNotEqual(
            {(e["type"], e["loan_id"]) for e in a["seeded_exceptions"]},
            {(e["type"], e["loan_id"]) for e in b["seeded_exceptions"]},
        )

    def test_generation_does_not_change_global_random_state(self):
        before = random.getstate()
        generate_samples(self.directory)
        self.assertEqual(before, random.getstate())

    def test_every_seeded_error_is_visible_in_csvs_and_no_extra_errors_exist(self):
        # Independently audit exported rows, using Decimal rather than generator
        # internals. This verifies M1's data contract; it is not the M2 engine.
        for seed, n_loans in ((42, 40), (7, 3), (0, 1), (5, 2), (99, 100)):
            with self.subTest(seed=seed, n_loans=n_loans):
                generate_samples(self.directory, seed=seed, n_loans=n_loans)
                manifest = json.loads((self.directory / "ground_truth.json").read_text())
                servicing = read_csv(self.directory / "servicing_extract.csv")
                payments = read_csv(self.directory / "payments_file.csv")
                investors = read_csv(self.directory / "investor_report.csv")
                self.assertEqual(len(servicing), n_loans)
                self.assertEqual(len(investors), n_loans)
                loan_ids = {row["LoanIdentifier"] for row in servicing}
                self.assertEqual(len(loan_ids), n_loans)
                self.assertEqual({row["Loan_ID"] for row in investors}, loan_ids)
                self.assertTrue({row["loan_ref"] for row in payments} <= loan_ids)
                self.assertEqual(len({row["PostingReference"] for row in payments}), len(payments))
                investor_by_loan = {row["Loan_ID"]: row for row in investors}
                postings = defaultdict(list)
                for payment in payments:
                    self.assertEqual(payment["payment_method"], "DIRECT_DEBIT")
                    self.assertEqual(payment["payment_period"], "2026-08")
                    postings[payment["loan_ref"]].append(payment)

                observed = set()
                for row in servicing:
                    loan_id = row["LoanIdentifier"]
                    investor = investor_by_loan[loan_id]
                    self.assertEqual(row["Period"], "2026-08")
                    self.assertEqual(investor["ReportMonth"], row["Period"])
                    scheduled = Decimal(row["ScheduledInstalment"])
                    self.assertGreater(scheduled, 0)
                    ledger = postings[loan_id]
                    received = sum((Decimal(p["amount_received"]) for p in ledger), Decimal(0))
                    self.assertEqual(Decimal(investor["ReportedCash"]), received)
                    if received == 0:
                        self.assertEqual(ledger, [])
                        observed.add(("MISSING_PAYMENT", loan_id))
                    elif len(ledger) > 1:
                        self.assertEqual(len(ledger), 2)
                        self.assertTrue(all(Decimal(p["amount_received"]) == scheduled for p in ledger))
                        self.assertEqual(received, scheduled * 2)
                        observed.add(("DUPLICATE_DIRECT_DEBIT", loan_id))
                    else:
                        self.assertEqual(received, scheduled)
                    charged = Decimal(investor["ChargedMarginPct"])
                    contractual = Decimal(row["ContractMarginPct"])
                    if charged > contractual:
                        observed.add(("RATE_MARGIN_BREACH", loan_id))
                    else:
                        self.assertEqual(charged, contractual)

                expected = {(e["type"], e["loan_id"]) for e in manifest["seeded_exceptions"]}
                self.assertEqual(expected, observed)
                self.assertEqual(manifest["seed"], seed)
                self.assertEqual(manifest["n_loans"], n_loans)
                self.assertEqual(manifest["exception_count"], len(expected))
                self.assertEqual(len(manifest["seeded_exceptions"]), len(expected))
                for error in manifest["seeded_exceptions"]:
                    self.assertEqual(set(error), {"type", "loan_id", "detail"})
                    self.assertIn(error["loan_id"], error["detail"])
                    self.assertIn("2026-08", error["detail"])
                if n_loans == 40:
                    self.assertEqual(Counter(t for t, _ in expected), {
                        "MISSING_PAYMENT": 4,
                        "DUPLICATE_DIRECT_DEBIT": 4,
                        "RATE_MARGIN_BREACH": 4,
                    })

    def test_headers_require_mapping_and_values_have_no_pii_patterns(self):
        generate_samples(self.directory)
        headers = []
        # Test the generated values, not the eventual runtime PII validator.
        pii = re.compile(
            r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
            r"|\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b"
            r"|(?<!\w)\+?\d(?:[ ().-]*\d){9,14}(?!\w)",
            re.IGNORECASE,
        )
        for filename in FILENAMES[:3]:
            with (self.directory / filename).open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                headers.append(set(reader.fieldnames))
                for row in reader:
                    for column, value in row.items():
                        self.assertIsNone(pii.search(value), (filename, column, value))
                        if column in {"LoanIdentifier", "loan_ref", "Loan_ID"}:
                            self.assertRegex(value, r"^SYN-L\d{6}$")
                        if column == "PostingReference":
                            self.assertRegex(value, r"^SYN-P\d{6}-[AB]$")
                        if column in {
                            "ScheduledInstalment", "ContractMarginPct",
                            "amount_received", "ReportedCash", "ChargedMarginPct",
                        }:
                            self.assertRegex(value, r"^\d+\.\d{2}$")
        self.assertFalse(headers[0] & headers[1])
        self.assertFalse(headers[1] & headers[2])
        self.assertFalse(headers[0] & headers[2])

    def test_manifest_details_quote_actual_source_amounts_and_margins(self):
        # A refreshed golden file can preserve an incorrect description. Check
        # the described quantities against CSV facts, not another generated key.
        def described_number(detail, pattern):
            match = re.search(pattern, detail)
            self.assertIsNotNone(match, detail)
            return Decimal(match.group(1))

        for seed, n_loans in ((42, 40), (7, 3), (99, 100)):
            generate_samples(self.directory, seed=seed, n_loans=n_loans)
            manifest = json.loads((self.directory / "ground_truth.json").read_text())
            servicing = {
                row["LoanIdentifier"]: row
                for row in read_csv(self.directory / "servicing_extract.csv")
            }
            investors = {
                row["Loan_ID"]: row
                for row in read_csv(self.directory / "investor_report.csv")
            }
            payments = read_csv(self.directory / "payments_file.csv")
            for exception in manifest["seeded_exceptions"]:
                loan_id, detail = exception["loan_id"], exception["detail"]
                row = servicing[loan_id]
                ledger = [p for p in payments if p["loan_ref"] == loan_id]
                received = sum((Decimal(p["amount_received"]) for p in ledger), Decimal(0))
                with self.subTest(seed=seed, loan_id=loan_id, type=exception["type"]):
                    if exception["type"] in {"MISSING_PAYMENT", "DUPLICATE_DIRECT_DEBIT"}:
                        self.assertEqual(
                            described_number(detail, r"scheduled (\d+\.\d{2})"),
                            Decimal(row["ScheduledInstalment"]),
                        )
                        self.assertEqual(
                            described_number(detail, r"received (\d+\.\d{2})"), received,
                        )
                    if exception["type"] == "DUPLICATE_DIRECT_DEBIT":
                        self.assertEqual(
                            described_number(detail, r"(\d+) direct-debit postings"), len(ledger),
                        )
                        posting_amount = described_number(detail, r"postings of (\d+\.\d{2})")
                        self.assertTrue(all(Decimal(p["amount_received"]) == posting_amount for p in ledger))
                        self.assertEqual(
                            described_number(detail, r"exactly (\d+) times"),
                            received / Decimal(row["ScheduledInstalment"]),
                        )
                    if exception["type"] == "RATE_MARGIN_BREACH":
                        charged = Decimal(investors[loan_id]["ChargedMarginPct"])
                        contractual = Decimal(row["ContractMarginPct"])
                        self.assertEqual(
                            described_number(detail, r"charged margin (\d+\.\d{2})%"), charged,
                        )
                        self.assertEqual(
                            described_number(detail, r"contractual margin (\d+\.\d{2})%"), contractual,
                        )
                        self.assertEqual(
                            described_number(detail, r"by (\d+\.\d{2}) percentage points"),
                            charged - contractual,
                        )

    def test_invalid_counts_do_not_create_output(self):
        target = self.directory / "invalid"
        for invalid in (0, -1, True, 1.5, "40"):
            with self.subTest(n_loans=invalid):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    generate_samples(target, n_loans=invalid)
                self.assertFalse(target.exists())

    def test_cli_runs_without_credentials_from_another_working_directory(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "data/generate_samples.py"), "--seed", "42",
             "--n-loans", "40", "--output-dir", str(self.directory / "cli")],
            cwd=self.directory, env={}, capture_output=True, text=True, check=True,
        )
        self.assertIn("40 loans, 12 seeded exceptions", result.stdout)
        for filename in FILENAMES:
            self.assertEqual(
                (self.directory / "cli" / filename).read_bytes(),
                (ROOT / "data/samples" / filename).read_bytes(),
            )

    def test_cli_rejects_nonpositive_count_with_a_clear_error(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "data/generate_samples.py"), "--n-loans", "0",
             "--output-dir", str(self.directory / "invalid")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--n-loans must be a positive integer", result.stderr)
        self.assertFalse((self.directory / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
