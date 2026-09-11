"""Upload hand-authored CSV packs twice through FastAPI and the real graph.

Run from the repository root: .venv/bin/python -m scripts.check_scenarios
The expected JSON is an external oracle; it is never sent to the application.
These tests use MockProvider, so repeated results do not establish LLM quality.
"""

import csv
import hashlib
import io
import json
import re
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


SCENARIOS = Path(__file__).resolve().parents[1] / "data" / "scenarios"
KINDS = ("servicing", "payments", "investor")
ZERO = Decimal("0.00")


def require(condition, message):
    # Do not use assert: running Python with -O must not disable this harness.
    if not condition:
        raise AssertionError(message)


def load_pack(entry):
    folder = SCENARIOS / entry["id"]
    files = {kind: (folder / entry["files"][kind]).read_text(encoding="utf-8") for kind in KINDS}
    mapping = json.loads((folder / "mapping.json").read_text())
    expected = json.loads((folder / "expected.json").read_text())
    return files, mapping, expected


def source_controls(entry, files, mapping, expected):
    """Independent CSV + Decimal arithmetic, with no engine/helper imports."""
    tables = {}
    for kind in KINDS:
        csv_text = files[kind]
        reader = csv.DictReader(io.StringIO(csv_text), strict=True)
        require(set(reader.fieldnames) == set(mapping[kind]), f"{entry['id']}: incomplete mapping for {kind}")
        tables[kind] = [{mapping[kind][raw]: value for raw, value in row.items()} for row in reader]
        require(len(tables[kind]) == expected["row_counts"][kind], f"{entry['id']}: {kind} row count")
        digest = hashlib.sha256(csv_text.encode()).hexdigest()
        require(digest == expected["sha256"][entry["files"][kind]], f"{entry['id']}: {kind} CSV changed")
        for row in tables[kind]:
            require(row["period"] == expected["period"], f"{entry['id']}: reporting period differs")
            require(re.fullmatch(r"SYN-L[0-9]{6}", row["loan_id"]), f"{entry['id']}: nonsynthetic loan reference")
            for field, value in row.items():
                if field.endswith("amount") or field.endswith("margin"):
                    require(re.fullmatch(r"-?[0-9]+\.[0-9]{2}", value), f"{entry['id']}: {field} must have two decimals")

    posting_ids = [row["posting_id"] for row in tables["payments"]]
    require(len(posting_ids) == len(set(posting_ids)), f"{entry['id']}: repeated posting reference")
    require(all(row["payment_method"] == "DIRECT_DEBIT" for row in tables["payments"]), f"{entry['id']}: unexpected payment route")
    accounts = []
    reports = {row["loan_id"]: row for row in tables["investor"]}
    require(len(reports) == expected["account_count"], f"{entry['id']}: investor account coverage")
    for source in tables["servicing"]:
        loan_id = source["loan_id"]
        entries = [row for row in tables["payments"] if row["loan_id"] == loan_id]
        scheduled = Decimal(source["scheduled_amount"])
        received = sum((Decimal(row["received_amount"]) for row in entries), ZERO)
        accounts.append({
            "loan_id": loan_id,
            "scheduled": f"{scheduled:.2f}", "received": f"{received:.2f}",
            "reported": reports[loan_id]["reported_amount"],
            "shortfall": f"{max(scheduled - received, ZERO):.2f}",
            "excess": f"{max(received - scheduled, ZERO):.2f}",
            "contractual_margin": source["contractual_margin"],
            "charged_margin": reports[loan_id]["charged_margin"],
            "posting_count": len(entries),
            "direct_debit_count": sum(row["payment_method"] == "DIRECT_DEBIT" for row in entries),
        })
    require(accounts == expected["accounts"], f"{entry['id']}: hand-authored account controls differ from CSVs")
    require(len(accounts) == expected["account_count"], f"{entry['id']}: account count differs")
    totals = {field: f"{sum((Decimal(row[field]) for row in accounts), ZERO):.2f}"
              for field in ("scheduled", "received", "reported", "shortfall", "excess")}
    totals["net_difference"] = f"{Decimal(totals['received']) - Decimal(totals['scheduled']):.2f}"
    require(totals == expected["totals"], f"{entry['id']}: hand-authored totals differ from CSVs")
    return accounts, totals


def stable_findings(findings):
    """Exclude run-specific absolute directories; retain raw evidence and IDs."""
    return [{**finding, "evidence": [{**row, "file": Path(row["file"]).name}
                                      for row in finding["evidence"]]} for finding in findings]


def check_evidence(entry, findings, files):
    filename_to_kind = {name: kind for kind, name in entry["files"].items()}
    for finding in findings:
        require(bool(finding["evidence"]), f"{entry['id']}: missing source evidence")
        for row in finding["evidence"]:
            kind = filename_to_kind[Path(row["file"]).name]
            lines = files[kind].splitlines(keepends=True)
            require(row["row_number"] >= 2, f"{entry['id']}: evidence points to a header")
            require(row["raw_text"] == lines[row["row_number"] - 1], f"{entry['id']}: raw CSV evidence changed")
            raw = next(csv.DictReader([lines[0], row["raw_text"]]))
            require(row["raw"] == raw, f"{entry['id']}: evidence values changed")


def check_payment_summary(entry, completed, expected):
    summary = completed["payment_summary"]
    require(summary["available"] is True, f"{entry['id']}: payment summary unavailable")
    require(summary["currency"] is None, f"{entry['id']}: currency was invented")
    require(summary["period"] == expected["period"], f"{entry['id']}: summary period differs")
    require(summary["account_count"] == expected["account_count"], f"{entry['id']}: summary account count differs")
    require(summary["accounts_with_findings"] == expected["affected_account_count"],
            f"{entry['id']}: issues were counted as distinct accounts")
    for field, wanted in expected["totals"].items():
        require(summary[field] == wanted, f"{entry['id']}: chart total {field} differs")
    projected = [{key: account[key] for key in expected["accounts"][0]}
                 for account in summary["accounts"]]
    require(projected == expected["accounts"], f"{entry['id']}: summary account arithmetic differs")
    cash_counts = {key: 0 for key in ("matched", "under", "over")}
    for account in expected["accounts"]:
        cash_status = "under" if Decimal(account["shortfall"]) > ZERO else "over" if Decimal(account["excess"]) > ZERO else "matched"
        cash_counts[cash_status] += 1
        returned = next(item for item in summary["accounts"] if item["loan_id"] == account["loan_id"])
        require(returned["cash_status"] == cash_status, f"{entry['id']}: chart payment status differs")
        wanted_types = {item["type"] for item in expected["findings"] if item["loan_id"] == account["loan_id"]}
        require(set(returned["issue_types"]) == wanted_types, f"{entry['id']}: summary issue types differ")
    require(summary["cash_counts"] == cash_counts, f"{entry['id']}: payment chart counts differ")
    expected_counts = Counter(item["type"] for item in expected["findings"])
    require(summary["issue_counts"] == {kind: expected_counts[kind] for kind in (
        "MISSING_PAYMENT", "DUPLICATE_DIRECT_DEBIT", "RATE_MARGIN_BREACH")},
        f"{entry['id']}: issue chart counts differ")


def upload_once(client, entry, files, mapping, expected):
    response = client.post("/runs", json={"provider": "mock", "files": files, "synthetic_data": True})
    require(response.status_code == 200, f"{entry['id']}: upload HTTP {response.status_code}")
    paused = response.json()
    require(paused["status"] == "awaiting_confirmation", f"{entry['id']}: did not pause for a human")
    require(paused["engine_exceptions"] == [], f"{entry['id']}: engine ran before confirmation")
    require(paused["score"] is None, f"{entry['id']}: upload received an invented ground-truth score")
    pipeline = client.app.state.runs[paused["run_id"]]
    require(pipeline.graph.get_state(pipeline.config).tasks[0].interrupts,
            f"{entry['id']}: missing real LangGraph interrupt")
    if entry["id"] == "unfamiliar_headers":
        require(all(not columns for columns in paused["proposed_mapping"].values()),
                "Unfamiliar headers unexpectedly became mock aliases; revise this manual-mapping exercise")
    # This is an automated integration test supplying known mapping choices.
    # It is not a record that the owner approved a production mapping.
    response = client.post(f"/runs/{paused['run_id']}/confirm", json={"mapping": mapping})
    require(response.status_code == 200, f"{entry['id']}: confirmation HTTP {response.status_code}")
    completed = response.json()
    require(completed["status"] == "complete", f"{entry['id']}: run did not complete")
    require(completed["score"] is None, f"{entry['id']}: upload received an invented ground-truth score")
    findings = completed["engine_exceptions"]
    observed = Counter((row["loan_id"], row["ex_type"]) for row in findings)
    wanted = Counter((row["loan_id"], row["type"]) for row in expected["findings"])
    require(observed == wanted, f"{entry['id']}: exact issue identities differ: {observed} != {wanted}")
    require(len({row["loan_id"] for row in findings}) == expected["affected_account_count"],
            f"{entry['id']}: distinct affected-account count differs")
    check_evidence(entry, findings, files)
    check_payment_summary(entry, completed, expected)
    analytics = client.get(f"/runs/{completed['run_id']}/analytics").json()
    operations = [span["name"] for span in analytics["span_timeline"]]
    require(operations.index("mapping_confirmed") < operations.index("reconcile_engine"),
            f"{entry['id']}: confirmation must precede calculations")
    require(all(call["provider"] == "mock" for call in analytics["model_calls"]), f"{entry['id']}: unexpected live model call")
    return completed, analytics


def check_invalid_uploads(client, entry):
    files, mapping, _ = load_pack(entry)
    before = len(client.get("/runs").json())
    incomplete = {kind: csv_text for kind, csv_text in files.items() if kind != "investor"}
    response = client.post("/runs", json={"files": incomplete, "provider": "mock"})
    require(response.status_code == 422, "Missing-file upload must be rejected")
    require(len(client.get("/runs").json()) == before, "Missing-file upload must not create a run")

    malformed = dict(files)
    malformed["servicing"] = malformed["servicing"].replace("1000.00", "not-a-number", 1)
    paused = client.post("/runs", json={"files": malformed, "provider": "mock"}).json()
    require(paused["status"] == "awaiting_confirmation", "Malformed number should remain reviewable before mapping confirmation")
    completed = client.post(f"/runs/{paused['run_id']}/confirm", json={"mapping": mapping}).json()
    require(completed["status"] == "error", "Malformed mapped number must stop calculations")
    require(completed["engine_exceptions"] == [] and completed["remediation_log"] == [],
            "Malformed mapped input must not publish findings")
    require(completed["score"] is None, "Malformed upload must not receive a fixture score")
    return ["missing_file_rejected_before_run", "malformed_amount_stops_after_confirmation"]


def check_scenarios():
    catalog = json.loads((SCENARIOS / "catalog.json").read_text())
    results = []
    with tempfile.TemporaryDirectory(prefix="uc1-csv-scenarios-") as temporary:
        app = create_app(storage=Path(temporary) / "runs", environ={})
        with TestClient(app) as client:
            for entry in catalog:
                files, mapping, expected = load_pack(entry)
                accounts, totals = source_controls(entry, files, mapping, expected)
                first, first_analytics = upload_once(client, entry, files, mapping, expected)
                second, _ = upload_once(client, entry, files, mapping, expected)
                require(first["run_id"] != second["run_id"], "Repeat must create a distinct run")
                require(stable_findings(first["engine_exceptions"]) == stable_findings(second["engine_exceptions"]),
                        f"{entry['id']}: repeated calculations/evidence changed")
                require(first["payment_summary"] == second["payment_summary"],
                        f"{entry['id']}: repeated dashboard account/graph figures changed")
                results.append({
                    "id": entry["id"], "accounts": len(accounts), "issues": len(first["engine_exceptions"]),
                    "affected_accounts": expected["affected_account_count"], "totals": totals,
                    "uploads_verified": 2, "model_calls_per_upload": len(first_analytics["model_calls"]),
                    "upload_score": first["score"],
                })
            invalid = check_invalid_uploads(client, catalog[0])
    return {"status": "passed", "provider": "mock", "packs": results,
            "uploads_verified": len(catalog) * 2, "invalid_upload_checks": invalid}


if __name__ == "__main__":
    print(json.dumps(check_scenarios(), indent=2))
