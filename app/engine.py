"""Deterministic, single-month reconciliation. All arithmetic uses integers.

The caller supplies a confirmed mapping. The structural human checkpoint is a
graph responsibility (M5); these functions neither call a model nor read an
answer key during detection. Incomplete mappings remain inspectable and skip
dependent detectors. Malformed mapped data raises ReconciliationInputError.
"""

import csv
import re
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from data.generate_samples import EXCEPTION_TYPES


CANONICAL_FIELDS = {
    "servicing": ("loan_id", "period", "scheduled_amount", "contractual_margin"),
    "payments": ("posting_id", "loan_id", "period", "received_amount", "payment_method"),
    "investor": ("loan_id", "period", "reported_amount", "charged_margin"),
}
FILE_KINDS = {
    "servicing_extract.csv": "servicing",
    "payments_file.csv": "payments",
    "investor_report.csv": "investor",
}
NUMERIC_FIELDS = {
    "scheduled_amount", "contractual_margin", "received_amount",
    "reported_amount", "charged_margin",
}


class ReconciliationInputError(ValueError):
    """Input violates the declared CSV, number or single-month contract."""


@dataclass
class MappedRow:
    values: dict[str, str]
    source: dict


@dataclass
class MappedFile:
    kind: str
    rows: list[MappedRow]
    mapped_fields: frozenset[str]
    issues: list[str]

    def supports(self, *fields: str) -> bool:
        return set(fields) <= self.mapped_fields


def load_mapped(path: Path | str, mapping: dict[str, str], *, kind: str | None = None) -> MappedFile:
    """Apply raw-header -> canonical names, preserving raw values and records.

    Standard fixture filenames identify the kind; renamed files need kind=.
    Missing mappings are diagnostics, never guessed aliases or invented zeros.
    row_number is the physical start line, including for multiline CSV records.
    """
    path = Path(path)
    kind = kind or FILE_KINDS.get(path.name)
    if kind not in CANONICAL_FIELDS:
        raise ReconciliationInputError("Specify kind='servicing', 'payments' or 'investor'")
    if not isinstance(mapping, dict) or not all(
        isinstance(raw, str) and isinstance(canonical, str)
        for raw, canonical in mapping.items()
    ):
        raise ReconciliationInputError("Mapping must be {raw_header: canonical_field}")
    unknown = set(mapping.values()) - set(CANONICAL_FIELDS[kind])
    if unknown:
        raise ReconciliationInputError(f"Unknown {kind} canonical fields: {sorted(unknown)}")
    if len(set(mapping.values())) != len(mapping):
        raise ReconciliationInputError("Two raw columns cannot map to the same canonical field")

    with path.open(encoding="utf-8-sig", newline="") as stream:
        lines = stream.readlines()
    reader = csv.reader(lines, strict=True)
    try:
        headers = next(reader, [])
        if not headers or any(not header for header in headers) or len(set(headers)) != len(headers):
            raise ReconciliationInputError(f"{path}: expected unique, nonempty CSV headers")
        active = {raw: canonical for raw, canonical in mapping.items() if raw in headers}
        fields = frozenset(active.values())
        issues = [f"{path.name}: mapped header {raw!r} is absent" for raw in mapping if raw not in headers]
        issues += [
            f"{path.name}: unmapped {field}; dependent detectors are skipped"
            for field in CANONICAL_FIELDS[kind] if field not in fields
        ]
        rows = []
        while True:
            start = reader.line_num
            record = next(reader, None)
            if record is None:
                break
            if not record:
                continue
            if len(record) != len(headers):
                raise ReconciliationInputError(f"{path}:{start + 1}: CSV field count differs from header")
            raw_row = dict(zip(headers, record))
            rows.append(MappedRow(
                values={canonical: raw_row[raw] for raw, canonical in active.items()},
                source={
                    "file": str(path.resolve()), "row_number": start + 1,
                    "raw": raw_row, "raw_text": "".join(lines[start:reader.line_num]),
                },
            ))
    except csv.Error as error:
        raise ReconciliationInputError(f"{path}:{reader.line_num}: invalid CSV: {error}") from error
    return MappedFile(kind, rows, fields, issues)


def _minor_units(value: str) -> int:
    """Parse a fixed-point amount/percentage without rounding or float context."""
    value = value.strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", value, flags=re.ASCII):
        raise ReconciliationInputError(f"Expected a finite number with at most 2 decimals, got {value!r}")
    negative = value.startswith("-")
    whole, _, fraction = value.lstrip("+-").partition(".")
    result = int(whole) * 100 + int(fraction.ljust(2, "0"))
    return -result if negative else result


def _display(value: int) -> str:
    magnitude = abs(value)
    return f"{'-' if value < 0 else ''}{magnitude // 100}.{magnitude % 100:02d}"


def _validate_and_index(table: MappedFile) -> dict[str, list[MappedRow]]:
    indexed = defaultdict(list)
    posting_ids = set()
    for row in table.rows:
        for field, value in row.values.items():
            try:
                if not value.strip():
                    raise ReconciliationInputError(f"Blank mapped {field}")
                if field in NUMERIC_FIELDS:
                    parsed = _minor_units(value)
                    if field in {"scheduled_amount", "contractual_margin", "charged_margin"} and parsed < 0:
                        raise ReconciliationInputError(f"Negative {field} is outside the input contract")
                if field == "period" and not re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", value):
                    raise ReconciliationInputError("Expected period YYYY-MM")
                if field in {"loan_id", "posting_id"} and value != value.strip():
                    raise ReconciliationInputError(f"Surrounding whitespace in {field}")
            except ReconciliationInputError as error:
                raise ReconciliationInputError(
                    f"{row.source['file']}:{row.source['row_number']}: {error}"
                ) from error
        if table.kind == "payments" and "posting_id" in row.values:
            posting_id = row.values["posting_id"]
            if posting_id in posting_ids:
                raise ReconciliationInputError(f"Repeated posting_id {posting_id!r}; cannot infer distinct debits")
            posting_ids.add(posting_id)
        loan_id = row.values.get("loan_id")
        if loan_id is not None:
            if table.kind != "payments" and indexed[loan_id]:
                raise ReconciliationInputError(f"Multiple {table.kind} rows for loan {loan_id!r}")
            indexed[loan_id].append(row)
    return dict(indexed)


def reconcile(servicing: MappedFile, payments: MappedFile, investor: MappedFile) -> list[dict]:
    """Return three closed-set exception patterns with unchanged source evidence.

    Missing = scheduled > 0 and total net cash received == 0, including reversals.
    Duplicate = >1 DIRECT_DEBIT postings, net >= 2 * scheduled and an exact
    scheduled multiple. This pattern cannot establish whether cash was authorised.
    Margin breach = charged margin strictly exceeds contractual margin.
    """
    tables = (servicing, payments, investor)
    if tuple(table.kind for table in tables) != ("servicing", "payments", "investor"):
        raise ReconciliationInputError("Expected servicing, payments and investor tables in that order")
    service_index, payment_index, investor_index = [_validate_and_index(table) for table in tables]
    periods = {row.values["period"] for table in tables for row in table.rows if "period" in row.values}
    if len(periods) > 1:
        raise ReconciliationInputError("All files must cover one consistent reporting month")
    if servicing.supports("loan_id"):
        for name, index in (("payments", payment_index), ("investor", investor_index)):
            unknown = set(index) - set(service_index)
            if unknown:
                raise ReconciliationInputError(f"{name} contains loans absent from servicing: {sorted(unknown)}")

    cash_ready = servicing.supports("loan_id", "period", "scheduled_amount") and payments.supports(
        "loan_id", "period", "received_amount",
    )
    duplicate_ready = cash_ready and payments.supports("posting_id", "payment_method")
    margin_ready = servicing.supports("loan_id", "period", "contractual_margin") and investor.supports(
        "loan_id", "period", "charged_margin",
    )
    found = []
    for loan_id in sorted(service_index):
        service = service_index[loan_id][0]
        ledger = payment_index.get(loan_id, [])
        report_rows = investor_index.get(loan_id, [])
        period = service.values.get("period")
        details = {}
        if cash_ready:
            scheduled = _minor_units(service.values["scheduled_amount"])
            received = sum(_minor_units(row.values["received_amount"]) for row in ledger)
            if scheduled > 0 and received == 0:
                details["MISSING_PAYMENT"] = (
                    f"Loan {loan_id}: scheduled {_display(scheduled)} for {period}; "
                    f"net received {_display(received)} across {len(ledger)} payment postings."
                )
            if duplicate_ready and scheduled > 0:
                debits = [row for row in ledger if row.values["payment_method"] == "DIRECT_DEBIT"]
                debit_net = sum(_minor_units(row.values["received_amount"]) for row in debits)
                if len(debits) > 1 and debit_net >= 2 * scheduled and debit_net % scheduled == 0:
                    details["DUPLICATE_DIRECT_DEBIT"] = (
                        f"Loan {loan_id}: {len(debits)} direct-debit postings net {_display(debit_net)} "
                        f"for {period}, exactly {debit_net // scheduled} times the scheduled "
                        f"{_display(scheduled)}; total net received {_display(received)}. "
                        "This matches the duplicate pattern; authorisation is not established."
                    )
        if margin_ready and report_rows:
            contractual = _minor_units(service.values["contractual_margin"])
            charged = _minor_units(report_rows[0].values["charged_margin"])
            if charged > contractual:
                details["RATE_MARGIN_BREACH"] = (
                    f"Loan {loan_id}: charged margin {_display(charged)}% exceeds contractual "
                    f"margin {_display(contractual)}% by {_display(charged - contractual)} "
                    f"percentage points for {period}."
                )
        for ex_type in EXCEPTION_TYPES:
            if ex_type in details:
                found.append({
                    "ex_id": f"{ex_type}:{period}:{loan_id}",
                    "ex_type": ex_type, "loan_id": loan_id, "detail": details[ex_type],
                    "evidence": [deepcopy(row.source) for row in [service, *ledger, *report_rows]],
                })
    return found


def _metrics(true_positives: int, false_positives: int, false_negatives: int) -> dict:
    return {
        "precision": true_positives / (true_positives + false_positives) if true_positives + false_positives else 1.0,
        "recall": true_positives / (true_positives + false_negatives) if true_positives + false_negatives else 1.0,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def score_against_ground_truth(found: list[dict], manifest: dict) -> dict:
    """Evaluate exception identities only; preserve missed/spurious entries.

    Each manifest entry can match only once: duplicate findings count as false
    positives. Unknown found types also count as false positives. The empty-set
    precision/recall convention is 1.0 with the accompanying counts made explicit.
    """
    expected = manifest["seeded_exceptions"]
    expected_keys = [(entry["type"], entry["loan_id"]) for entry in expected]
    if len(set(expected_keys)) != len(expected_keys):
        raise ValueError("Ground truth has duplicate (type, loan_id) entries")
    if any(ex_type not in EXCEPTION_TYPES for ex_type, _ in expected_keys):
        raise ValueError("Ground truth contains an unknown exception type")
    remaining = set(expected_keys)
    matched = Counter()
    spurious = []
    for entry in found:
        key = (entry["ex_type"], entry["loan_id"])
        if key in remaining:
            remaining.remove(key)
            matched[key[0]] += 1
        else:
            spurious.append(deepcopy(entry))
    missed = [deepcopy(entry) for entry in expected if (entry["type"], entry["loan_id"]) in remaining]
    types = list(EXCEPTION_TYPES) + sorted({entry["ex_type"] for entry in spurious} - set(EXCEPTION_TYPES))
    result = _metrics(sum(matched.values()), len(spurious), len(missed))
    result.update({
        "per_type": {
            ex_type: _metrics(
                matched[ex_type], sum(entry["ex_type"] == ex_type for entry in spurious),
                sum(entry["type"] == ex_type for entry in missed),
            )
            for ex_type in types
        },
        "missed": missed, "spurious": spurious,
    })
    return result
