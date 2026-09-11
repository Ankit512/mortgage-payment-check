"""R2 acceptance plus hand-authored numerical and input-boundary cases."""

import ast
import csv
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from app.engine import ReconciliationInputError, load_mapped, reconcile, score_against_ground_truth


ROOT = Path(__file__).resolve().parents[1]
KINDS = ("servicing", "payments", "investor")
FILENAMES = ("servicing_extract.csv", "payments_file.csv", "investor_report.csv")
MAPPINGS = {
    "servicing": {
        "LoanIdentifier": "loan_id", "Period": "period",
        "ScheduledInstalment": "scheduled_amount", "ContractMarginPct": "contractual_margin",
    },
    "payments": {
        "PostingReference": "posting_id", "loan_ref": "loan_id", "payment_period": "period",
        "amount_received": "received_amount", "payment_method": "payment_method",
    },
    "investor": {
        "Loan_ID": "loan_id", "ReportMonth": "period",
        "ReportedCash": "reported_amount", "ChargedMarginPct": "charged_margin",
    },
}


def audit_engine_imports(root):
    """Walk local imports and package initialisers; prohibit providers/externals."""
    visited = set()

    def locate(module):
        relative = root.joinpath(*module.split("."))
        for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
            if candidate.is_file():
                return candidate
        return None

    def visit(module):
        if module in visited:
            return
        visited.add(module)
        if module == "app.providers" or module.startswith("app.providers."):
            raise AssertionError(f"Engine reaches LLM provider seam: {module}")
        path = locate(module)
        if path is None:
            if module.split(".")[0] not in sys.stdlib_module_names:
                raise AssertionError(f"Engine reaches non-stdlib import: {module}")
            return
        parts = module.split(".")
        for index in range(1, len(parts)):
            visit(".".join(parts[:index]))
        package = parts if path.name == "__init__.py" else parts[:-1]
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    visit(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = package[:len(package) - node.level + 1] if node.level else []
                if node.module:
                    base += node.module.split(".")
                base_name = ".".join(base)
                if base_name:
                    visit(base_name)
                for alias in node.names:
                    child = ".".join([*base, alias.name])
                    if locate(child):
                        visit(child)
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                if name in {"__import__", "import_module", "exec", "eval"}:
                    raise AssertionError(f"Dynamic execution hides imports in {module}")
    visit("app.engine")
    return visited


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write_tables(self, servicing, payments, investor):
        tables = []
        for kind, filename, rows in zip(KINDS, FILENAMES, (servicing, payments, investor)):
            path = self.directory / filename
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=MAPPINGS[kind], lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            tables.append(load_mapped(path, MAPPINGS[kind]))
        return tables

    def case(self, amounts=(), *, scheduled="1000.00", contractual="2.00", charged="2.00", methods=None):
        methods = methods or ["DIRECT_DEBIT"] * len(amounts)
        return self.write_tables(
            [{"LoanIdentifier": "CASE-A", "Period": "2026-08", "ScheduledInstalment": scheduled,
              "ContractMarginPct": contractual}],
            [{"PostingReference": f"POST-{index}", "loan_ref": "CASE-A", "payment_period": "2026-08",
              "amount_received": amount, "payment_method": methods[index]}
             for index, amount in enumerate(amounts)],
            [{"Loan_ID": "CASE-A", "ReportMonth": "2026-08",
              "ReportedCash": str(sum((Decimal(a) for a in amounts), Decimal(0))),
              "ChargedMarginPct": charged}],
        )

    def fixtures(self):
        return [load_mapped(ROOT / "data/samples" / filename, MAPPINGS[kind])
                for kind, filename in zip(KINDS, FILENAMES)]

    def test_seed_42_engine_has_perfect_recall_and_zero_false_positives(self):
        tables = self.fixtures()
        self.assertTrue(all(not table.issues for table in tables))
        found = reconcile(*tables)
        manifest = json.loads((ROOT / "data/samples/ground_truth.json").read_text())
        score = score_against_ground_truth(found, manifest)
        self.assertEqual(len(found), 12)
        self.assertEqual(score["precision"], 1.0)
        self.assertEqual(score["recall"], 1.0)
        self.assertEqual(score["false_positives"], 0)
        self.assertEqual(score["missed"], [])
        self.assertEqual(score["spurious"], [])
        for metrics in score["per_type"].values():
            self.assertEqual(metrics["true_positives"], 4)
            self.assertEqual(metrics["recall"], 1.0)
        for exception in found:
            self.assertEqual(set(exception), {"ex_id", "ex_type", "loan_id", "detail", "evidence"})
            self.assertGreaterEqual(len(exception["evidence"]), 1)
            for source in exception["evidence"]:
                with Path(source["file"]).open(newline="") as stream:
                    lines = stream.readlines()
                self.assertEqual(source["raw_text"], lines[source["row_number"] - 1])
                self.assertIn(exception["loan_id"], source["raw"].values())

    def test_missing_means_zero_net_cash_including_reversals(self):
        for amounts in ((), ("0.00",), ("1000.00", "-1000.00")):
            with self.subTest(amounts=amounts):
                found = reconcile(*self.case(amounts))
                self.assertEqual([e["ex_type"] for e in found], ["MISSING_PAYMENT"])
                self.assertIn("net received 0.00", found[0]["detail"])
                self.assertIn(f"across {len(amounts)} payment postings", found[0]["detail"])
                # No invented zero payment evidence when the ledger is empty.
                self.assertEqual(len(found[0]["evidence"]), 2 + len(amounts))

    def test_partial_positive_and_negative_net_cash_are_not_zero_net_missing(self):
        for amount in ("0.01", "500.00", "1000.00", "-0.01"):
            with self.subTest(amount=amount):
                self.assertEqual(reconcile(*self.case((amount,))), [])

    def test_zero_schedule_does_not_divide_by_zero_or_create_cash_exceptions(self):
        self.assertEqual(reconcile(*self.case(("1000.00", "1000.00"), scheduled="0.00")), [])
        self.assertEqual(reconcile(*self.case(scheduled="0.00")), [])

    def test_two_and_three_full_debits_match_the_duplicate_pattern(self):
        for count in (2, 3):
            with self.subTest(count=count):
                found = reconcile(*self.case(("1000.00",) * count))
                self.assertEqual([e["ex_type"] for e in found], ["DUPLICATE_DIRECT_DEBIT"])
                self.assertIn(f"exactly {count} times", found[0]["detail"])
                self.assertIn("authorisation is not established", found[0]["detail"])

    def test_split_payments_single_overpayment_and_reversed_duplicate_are_negative_cases(self):
        cases = (
            ("500.00", "500.00"), ("2000.00",),
            ("1000.00", "1000.00", "-1000.00"),
            ("1000.00", "999.99"), ("1000.00", "1000.00", "10.00"),
        )
        for amounts in cases:
            with self.subTest(amounts=amounts):
                self.assertEqual(reconcile(*self.case(amounts)), [])

    def test_unequal_postings_can_match_the_declared_net_multiple_pattern(self):
        found = reconcile(*self.case(("1500.00", "500.00")))
        self.assertEqual([e["ex_type"] for e in found], ["DUPLICATE_DIRECT_DEBIT"])
        self.assertIn("net 2000.00", found[0]["detail"])

    def test_direct_debit_net_is_separate_from_other_payment_methods(self):
        self.assertEqual(reconcile(*self.case(
            ("1000.00", "1000.00"), methods=["BANK_TRANSFER", "BANK_TRANSFER"],
        )), [])
        self.assertEqual(reconcile(*self.case(
            ("1000.00", "1000.00"), methods=["DIRECT_DEBIT", "BANK_TRANSFER"],
        )), [])
        found = reconcile(*self.case(
            ("1000.00", "1000.00", "10.00"),
            methods=["DIRECT_DEBIT", "DIRECT_DEBIT", "BANK_TRANSFER"],
        ))
        self.assertEqual([e["ex_type"] for e in found], ["DUPLICATE_DIRECT_DEBIT"])
        self.assertIn("total net received 2010.00", found[0]["detail"])

    def test_exact_cents_and_large_amounts_do_not_use_float_rounding(self):
        self.assertEqual(reconcile(*self.case(("0.10", "0.20"), scheduled="0.30")), [])
        found = reconcile(*self.case(("0.10", "0.20", "0.30"), scheduled="0.30"))
        self.assertEqual([e["ex_type"] for e in found], ["DUPLICATE_DIRECT_DEBIT"])
        big = "9007199254740993.01"
        found = reconcile(*self.case((big, big), scheduled=big))
        self.assertIn("net 18014398509481986.02", found[0]["detail"])

    def test_margin_is_strict_and_uses_percentage_point_difference(self):
        for charged, expected in (("1.99", []), ("2.00", []), ("2.01", ["RATE_MARGIN_BREACH"])):
            with self.subTest(charged=charged):
                found = reconcile(*self.case(("1000.00",), charged=charged))
                self.assertEqual([e["ex_type"] for e in found], expected)
                if expected:
                    self.assertIn("by 0.01 percentage points", found[0]["detail"])

    def test_cash_and_rate_exceptions_can_overlap_on_one_loan(self):
        found = reconcile(*self.case(charged="2.25"))
        self.assertEqual([e["ex_type"] for e in found], ["MISSING_PAYMENT", "RATE_MARGIN_BREACH"])
        self.assertEqual(len({e["ex_id"] for e in found}), 2)

    def test_matching_is_per_loan_even_when_aggregate_cash_balances(self):
        tables = self.write_tables(
            [{"LoanIdentifier": loan, "Period": "2026-08", "ScheduledInstalment": "1000.00",
              "ContractMarginPct": "2.00"} for loan in ("CASE-A", "CASE-B")],
            [{"PostingReference": f"POST-{n}", "loan_ref": "CASE-B", "payment_period": "2026-08",
              "amount_received": "1000.00", "payment_method": "DIRECT_DEBIT"} for n in (1, 2)],
            [{"Loan_ID": loan, "ReportMonth": "2026-08", "ReportedCash": cash, "ChargedMarginPct": "2.00"}
             for loan, cash in (("CASE-A", "0.00"), ("CASE-B", "2000.00"))],
        )
        self.assertEqual([(e["ex_type"], e["loan_id"]) for e in reconcile(*tables)], [
            ("MISSING_PAYMENT", "CASE-A"), ("DUPLICATE_DIRECT_DEBIT", "CASE-B"),
        ])

    def test_unmapped_amounts_skip_checks_and_are_exposed_as_missed_exceptions(self):
        manifest = json.loads((ROOT / "data/samples/ground_truth.json").read_text())
        for kind, omitted in (("servicing", "ScheduledInstalment"), ("payments", "amount_received")):
            with self.subTest(kind=kind):
                tables = self.fixtures()
                mapping = {raw: canonical for raw, canonical in MAPPINGS[kind].items() if raw != omitted}
                index = KINDS.index(kind)
                tables[index] = load_mapped(ROOT / "data/samples" / FILENAMES[index], mapping)
                self.assertTrue(tables[index].issues)
                score = score_against_ground_truth(reconcile(*tables), manifest)
                self.assertEqual(score["recall"], 1 / 3)
                self.assertEqual(score["false_positives"], 0)
                self.assertEqual(len(score["missed"]), 8)
                self.assertEqual(score["missed"], [
                    e for e in manifest["seeded_exceptions"] if e["type"] != "RATE_MARGIN_BREACH"
                ])

    def test_plausible_but_wrong_numeric_mapping_lowers_the_score(self):
        tables = self.fixtures()
        mapping = dict(MAPPINGS["servicing"])
        mapping["ScheduledInstalment"] = "contractual_margin"
        mapping["ContractMarginPct"] = "scheduled_amount"
        tables[0] = load_mapped(ROOT / "data/samples/servicing_extract.csv", mapping)
        self.assertEqual(tables[0].issues, [])
        manifest = json.loads((ROOT / "data/samples/ground_truth.json").read_text())
        score = score_against_ground_truth(reconcile(*tables), manifest)
        self.assertLess(score["recall"], 1.0)
        self.assertTrue(score["missed"])

    def test_missing_raw_header_is_reported_without_alias_guessing(self):
        mapping = dict(MAPPINGS["servicing"])
        mapping["UnknownAmount"] = mapping.pop("ScheduledInstalment")
        table = load_mapped(ROOT / "data/samples/servicing_extract.csv", mapping)
        self.assertNotIn("scheduled_amount", table.rows[0].values)
        self.assertTrue(any("UnknownAmount" in issue for issue in table.issues))

    def test_mapping_collisions_and_unknown_canonical_fields_are_rejected(self):
        for mapping in ({"LoanIdentifier": "loan_id", "Period": "loan_id"}, {"LoanIdentifier": "invented"}):
            with self.subTest(mapping=mapping), self.assertRaises(ReconciliationInputError):
                load_mapped(ROOT / "data/samples/servicing_extract.csv", mapping)

    def test_malformed_mapped_numbers_are_clear_errors_not_silent_zeros(self):
        for value in ("", "NaN", "Infinity", "1000.001", "1,000.00", "wrong"):
            with self.subTest(value=value):
                tables = self.case()
                tables[0].rows[0].values["scheduled_amount"] = value
                with self.assertRaisesRegex(ReconciliationInputError, "servicing_extract.csv:2"):
                    reconcile(*tables)

    def test_month_mismatch_and_invalid_period_are_rejected(self):
        for period in ("2026-09", "2026-13", "2026-08-31"):
            with self.subTest(period=period):
                tables = self.case(("1000.00",))
                tables[1].rows[0].values["period"] = period
                with self.assertRaises(ReconciliationInputError):
                    reconcile(*tables)

    def test_duplicate_source_keys_and_orphan_loans_are_rejected(self):
        for mutation in ("posting_id", "service_row", "investor_row", "orphan"):
            with self.subTest(mutation=mutation):
                tables = self.case(("1000.00", "1000.00"))
                if mutation == "posting_id":
                    tables[1].rows[1].values["posting_id"] = tables[1].rows[0].values["posting_id"]
                elif mutation == "service_row":
                    tables[0].rows.append(deepcopy(tables[0].rows[0]))
                elif mutation == "investor_row":
                    tables[2].rows.append(deepcopy(tables[2].rows[0]))
                else:
                    tables[1].rows[0].values["loan_id"] = "UNKNOWN"
                with self.assertRaises(ReconciliationInputError):
                    reconcile(*tables)

    def test_csv_shape_errors_are_rejected(self):
        path = self.directory / "servicing_extract.csv"
        for content in ("", "A,A\n1,2\n", "A,B\n1,2,3\n", 'A,B\n"unterminated,2\n'):
            with self.subTest(content=content):
                path.write_text(content)
                with self.assertRaises(ReconciliationInputError):
                    load_mapped(path, {})

    def test_quoted_multiline_evidence_retains_verbatim_record_and_line_number(self):
        tables = self.case()
        path = self.directory / "renamed.csv"
        header = "LoanIdentifier,Period,ScheduledInstalment,ContractMarginPct,Note\r\n"
        record = '"CASE-A",2026-08,1000.00,2.00,"audit, note\r\nline 2"\r\n'
        path.write_bytes((header + record).encode())
        tables[0] = load_mapped(path, MAPPINGS["servicing"], kind="servicing")
        source = reconcile(*tables)[0]["evidence"][0]
        self.assertEqual(source["row_number"], 2)
        self.assertEqual(source["raw_text"], record)
        self.assertEqual(source["raw"]["Note"], "audit, note\r\nline 2")
        self.assertEqual(source["raw"]["ScheduledInstalment"], "1000.00")

    def test_reconcile_is_repeatable_and_does_not_mutate_inputs(self):
        tables = self.fixtures()
        before = deepcopy(tables)
        first = reconcile(*tables)
        second = reconcile(*tables)
        self.assertEqual(first, second)
        self.assertEqual(tables, before)
        json.dumps(first)  # Results, including evidence, are directly JSON serialisable.
        first[0]["evidence"][0]["raw"]["LoanIdentifier"] = "ALTERED"
        self.assertEqual(tables, before)
        self.assertEqual(reconcile(*tables), second)

    def test_empty_but_correctly_mapped_files_return_no_exceptions(self):
        self.assertEqual(reconcile(*self.write_tables([], [], [])), [])

    def test_engine_import_graph_contains_only_stdlib_and_local_non_provider_modules(self):
        visited = audit_engine_imports(ROOT)
        self.assertIn("app.engine", visited)
        self.assertIn("data.generate_samples", visited)

    def test_import_guard_rejects_indirect_llm_imports_and_package_side_effects(self):
        app = self.directory / "app"
        app.mkdir()
        (app / "__init__.py").write_text("")
        (app / "engine.py").write_text("from . import bridge\n")
        (app / "bridge.py").write_text("import openai\n")
        with self.assertRaisesRegex(AssertionError, "non-stdlib import: openai"):
            audit_engine_imports(self.directory)
        (app / "bridge.py").write_text("")
        (app / "__init__.py").write_text("from . import providers\n")
        (app / "providers.py").write_text("# Even a mock provider is outside the engine boundary.\n")
        with self.assertRaisesRegex(AssertionError, "provider seam"):
            audit_engine_imports(self.directory)


class ScoringTests(unittest.TestCase):
    def test_missed_spurious_and_duplicate_findings_are_counted_and_preserved(self):
        missing = {"type": "MISSING_PAYMENT", "loan_id": "A", "detail": "original missed detail"}
        duplicate = {"type": "DUPLICATE_DIRECT_DEBIT", "loan_id": "B", "detail": "original expected detail"}
        found = [
            {"ex_type": "DUPLICATE_DIRECT_DEBIT", "loan_id": "B", "ex_id": "first"},
            {"ex_type": "DUPLICATE_DIRECT_DEBIT", "loan_id": "B", "ex_id": "repeated"},
            {"ex_type": "INVENTED", "loan_id": "C", "detail": "preserve me"},
        ]
        manifest = {"seeded_exceptions": [missing, duplicate]}
        before = deepcopy((found, manifest))
        score = score_against_ground_truth(found, manifest)
        self.assertEqual(score["true_positives"], 1)
        self.assertEqual(score["false_positives"], 2)
        self.assertEqual(score["false_negatives"], 1)
        self.assertEqual(score["precision"], 1 / 3)
        self.assertEqual(score["recall"], 1 / 2)
        self.assertEqual(score["missed"], [missing])
        self.assertEqual(score["spurious"], found[1:])
        self.assertEqual(score["per_type"]["INVENTED"]["false_positives"], 1)
        self.assertEqual(score["per_type"]["DUPLICATE_DIRECT_DEBIT"]["precision"], 1 / 2)
        self.assertEqual((found, manifest), before)

    def test_empty_denominator_conventions_are_explicit(self):
        score = score_against_ground_truth([], {"seeded_exceptions": []})
        self.assertEqual((score["precision"], score["recall"]), (1.0, 1.0))
        score = score_against_ground_truth([], {"seeded_exceptions": [
            {"type": "MISSING_PAYMENT", "loan_id": "A", "detail": "unpaid"},
        ]})
        self.assertEqual((score["precision"], score["recall"]), (1.0, 0.0))
        self.assertEqual(score["false_negatives"], 1)

    def test_duplicate_or_unknown_expected_types_do_not_corrupt_the_score(self):
        entry = {"type": "MISSING_PAYMENT", "loan_id": "A", "detail": "unpaid"}
        for entries in ([entry, entry], [{"type": "INVENTED", "loan_id": "B"}]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                score_against_ground_truth([], {"seeded_exceptions": entries})


if __name__ == "__main__":
    unittest.main()
