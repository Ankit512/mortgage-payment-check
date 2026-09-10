# Synthetic sample contract

These files model one reporting month, `2026-08`, in one unspecified currency.
Amounts are nominal fixture values, not a mortgage amortisation model. Identifiers
such as `SYN-L000001` and `SYN-P000001-A` are invented. There are no borrower names,
addresses, phone numbers, emails or bank account numbers.

| File | Raw column | Meaning / intended canonical field |
| --- | --- | --- |
| servicing_extract.csv | LoanIdentifier | `loan_id` |
| servicing_extract.csv | Period | `period` (YYYY-MM) |
| servicing_extract.csv | ScheduledInstalment | `scheduled_amount`, two decimal places |
| servicing_extract.csv | ContractMarginPct | `contractual_margin`, percentage units |
| payments_file.csv | PostingReference | `posting_id`, unique for each posting |
| payments_file.csv | loan_ref | `loan_id` |
| payments_file.csv | payment_period | `period` |
| payments_file.csv | amount_received | `received_amount`, two decimal places |
| payments_file.csv | payment_method | `payment_method`, always DIRECT_DEBIT in M1 |
| investor_report.csv | Loan_ID | `loan_id` |
| investor_report.csv | ReportMonth | `period` |
| investor_report.csv | ReportedCash | `reported_amount`, equals actual payments sum |
| investor_report.csv | ChargedMarginPct | `charged_margin`, percentage units |

For example, a margin of `2.50` means 2.50%, or 250 basis points. Charged and
contractual margins use the same units. A difference of `0.25` is 0.25 percentage
points, or 25 basis points; these columns are not total mortgage interest rates.

## Seeded errors

The generator selects `min(N, 3 * max(1, N // 10))` distinct loans with a private
seeded random generator, then cycles through the three exception types. For
40 loans, 12 are affected and 28 are clean. For N >= 3 all three types appear;
N = 1 or 2 can cover only the first one or two types. N must be positive.

| Type | How it is inserted | How to verify it in the CSVs |
| --- | --- | --- |
| MISSING_PAYMENT | Omit the loan's payment posting. | Servicing scheduled amount is positive, payments has no matching loan/month, and investor cash is 0.00. |
| DUPLICATE_DIRECT_DEBIT | Write two equal direct-debit postings with distinct posting IDs. | Sum both postings: total is exactly twice the scheduled amount. Investor cash agrees with that total. |
| RATE_MARGIN_BREACH | Increase the charged margin by 25 to 100 basis points. | Investor charged margin exceeds servicing contractual margin; payment remains normal. |

Missing payments are an absence of postings, not invented zero-amount payment
rows. A duplicate means two ledger postings, not a repeated posting identifier.
The investor cash column agrees with the ledger even when cash is missing or
duplicated; this avoids introducing an unrequested fourth error type.

`ground_truth.json` records `{seed, n_loans, seeded_exceptions, exception_count}`.
Each exception has `{type, loan_id, detail}`. To audit an entry, filter all three
CSVs by its loan ID and month, then apply the relevant check in the table above.
The manifest is evaluation data; later stages must detect errors from the CSVs.

Reproducibility comes from fixed inputs, a fixed month, stable ordering, a local
random generator, and explicit UTF-8/LF/two-decimal formatting. Repeatability
alone does not prove correctness: tests independently read the exports and check
that every seeded error is present and no additional errors were introduced.

The first fixtures deliberately omit partial payments, reversals, multiple
months, currencies, overlapping exceptions, and malformed input. Later engine
tests must exercise the numerical boundary cases independently of these samples.
