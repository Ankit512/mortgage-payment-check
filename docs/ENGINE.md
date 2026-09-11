# M2: deterministic engine contract

`app/engine.py` implements R2 with standard-library dependencies. Numerical work
uses integer cents and integer basis points. The existing closed exception-type
constant is imported from `data.generate_samples`; the engine never invokes
generation or consults a manifest while reconciling. Scoring is a separate call.

## Interface

`load_mapped(path, mapping, *, kind=None) -> MappedFile` applies an explicitly
supplied `{raw_header: canonical_field}` mapping. Standard sample filenames
identify their kind; renamed files need `kind="servicing"`, `"payments"` or
`"investor"`. `CANONICAL_FIELDS` lists the supported fields per kind.

The returned table contains mapped rows, mapped field names, and `issues`.
Each row retains its original raw fields and exact CSV record text, including
quoting and line endings, with source filename and physical starting line number.
Mapping changes field names only. It does not infer aliases, convert rate units
or replace missing amounts with zeros.

`reconcile(servicing, payments, investor) -> list[dict]` validates the input
contract and runs the detectors. It returns `{ex_id, ex_type, loan_id, detail,
evidence}` per exception. IDs are stable combinations of type, period and loan.
Evidence includes the servicing row, available payment rows and available
investor row for that loan. No payment row is fabricated to represent absence.
Returned evidence is copied so callers cannot mutate the loaded rows through it.

`score_against_ground_truth(found, manifest)` compares `(type, loan_id)` identities
and reports overall/per-type precision, recall and counts, plus unmodified
`missed` manifest entries and `spurious` found entries. A repeated finding matches
only once; further copies count as false positives. Unknown found types remain
visible as false positives. Duplicate/unknown expected types are invalid answer
keys. With an empty denominator, the metric is 1.0 and the counts are explicit:
no predictions against nonempty truth therefore has precision 1.0 and recall 0.0.
Scores do not verify exception prose, authorisation or real-world performance.

## Numerical rules and limits

| Type | Rule | Important boundaries |
| --- | --- | --- |
| MISSING_PAYMENT | Scheduled > 0 and net sum of all payment methods == 0. | A debit followed by a complete reversal satisfies this rule. Positive partial receipts and negative net receipts do not. The detail describes zero net cash rather than asserting no posting occurred. |
| DUPLICATE_DIRECT_DEBIT | More than one DIRECT_DEBIT posting, whose net sum is an exact scheduled multiple >= 2, with scheduled > 0. | 500 + 500 against 1000 is excluded; 1500 + 500 is included; 1000 + 1000 + 10 in direct debits is excluded. These are declared pattern boundaries, not authorisation decisions. |
| RATE_MARGIN_BREACH | Charged margin > contractual margin, in the same percentage units. | Equality is clean. 2.01% minus 2.00% is 0.01 percentage points. |

Cash and margin exceptions can coexist on one loan. Duplicate netting considers
DIRECT_DEBIT rows only; missing-payment netting considers all payment methods.
Other methods do not turn a bank transfer into a duplicate direct debit. A
cross-method refund cannot establish settlement or authorisation history here.

The one-month input contract is validated across all mapped period values.
Different months are rejected; no multi-month matching subsystem is implemented.
Amounts and margins accept signed fixed-point decimal text with at most two
decimal places. Receipts and reported cash may be negative; scheduled amounts
and margins must be nonnegative. No floats, rounding, scientific notation,
thousands separators or nonfinite values are accepted. Percentages are already
expressed in percentage units, as documented in `data/README.md`.

Duplicate servicing/investor loan rows, repeated payment posting IDs, orphan
payment/investor loan IDs, malformed CSV records and malformed mapped values
raise `ReconciliationInputError` with an explanation. A repeated posting ID is
ambiguous source data, not automatically a second distinct debit.

An unmapped required field is different from a malformed mapped value: the
loader records an issue and affected detectors are skipped. On seed 42, removing
`scheduled_amount` or `received_amount` leaves the four rate breaches, precision
1.0, recall 1/3, and eight verbatim missed entries. A numerically parseable but
incorrect mapping can also lower the score despite having no structural mapping
issues. This makes R2's wrong-mapping demonstration inspectable. Callers must
present table issues alongside results; no PASS/BLOCK verdict is emitted here.

Missing investor rows provide no charged margin to compare. Investor reported
cash is retained as evidence but is not a fourth detector. Empty, correctly
headed files are supported. File completeness is not established by an empty
exception list. No data normalisation, financial authorisation handling or LLM
failure handling is implemented in M2.

## Runnable engine example

From the repository root, use this explicit mapping of the synthetic fixture.
This exercises the engine API; M5 will enforce confirmation structurally in the
graph. It is not an implementation of that future checkpoint.

```bash
python3 - <<'PY'
import json
from pathlib import Path
from app.engine import load_mapped, reconcile, score_against_ground_truth

samples = Path("data/samples")
servicing = load_mapped(samples / "servicing_extract.csv", {
    "LoanIdentifier": "loan_id", "Period": "period",
    "ScheduledInstalment": "scheduled_amount", "ContractMarginPct": "contractual_margin",
})
payments = load_mapped(samples / "payments_file.csv", {
    "PostingReference": "posting_id", "loan_ref": "loan_id", "payment_period": "period",
    "amount_received": "received_amount", "payment_method": "payment_method",
})
investor = load_mapped(samples / "investor_report.csv", {
    "Loan_ID": "loan_id", "ReportMonth": "period",
    "ReportedCash": "reported_amount", "ChargedMarginPct": "charged_margin",
})
exceptions = reconcile(servicing, payments, investor)
manifest = json.loads((samples / "ground_truth.json").read_text())
print(json.dumps({
    "issues": servicing.issues + payments.issues + investor.issues,
    "exceptions": exceptions,
    "score": score_against_ground_truth(exceptions, manifest),
}, indent=2))
PY
```

Run all verification with `python3 -m unittest discover tests -v`. At M2
completion there were 37 tests (9 M1, 28 M2); README tracks the current total.
Beyond seed-42 acceptance, hand-authored cases exercise arithmetic
boundaries, per-loan matching even when file totals agree, wrong mappings, raw
multiline evidence, input errors, scoring and purity. An AST import walk follows
local dependencies and package initialisers, rejects provider/non-stdlib imports
and dynamic import mechanisms, and is itself tested against indirect imports.
It is an architectural regression check, not a sandbox or proof against arbitrary
malicious code.
