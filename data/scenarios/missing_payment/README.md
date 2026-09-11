# A payment is missing

Three mortgage accounts. One has 1,500.00 due and no payment entry for the month.

1 issue on 1 account. Received money is 1,500.00 below the amount due.

These are invented mortgage records for August 2026. Amounts have two decimal places. No currency is specified by the CSV contract.

## Try this example

1. Start a new file check and choose the upload option.
2. Upload all three CSVs from this folder into their matching file slots.
3. Review the column choices below, approve them yourself, then run the checks.
4. Compare the result with the expected outcome. Upload the same files again to check that the numerical results repeat.

Use the mock provider for a quick deterministic walkthrough. It does not test the quality of Qwen's wording.

## Expected outcome

- SYN-L000201 has 1,500.00 due, zero payment entries and zero cash shown on the investor report.
- The other two accounts have the expected payments.

| Measure | Expected |
| --- | ---: |
| Accounts | 3 |
| Issues | 1 |
| Accounts with an issue | 1 |
| Amount due | 3000.25 |
| Net money received | 1500.25 |
| Investor-reported cash | 1500.25 |
| Received minus due | -1500.00 |
| Total account shortfalls | 1500.00 |
| Total account excess receipts | 0.00 |

Shortfall and excess are calculated separately for each account before adding them up. An issue count covers the three implemented checks; it is not proof that every possible mortgage error was checked.

## Column choices

| File | CSV heading | Choose this field |
| --- | --- | --- |
| servicing | LoanIdentifier | loan_id |
| servicing | Period | period |
| servicing | ScheduledInstalment | scheduled_amount |
| servicing | ContractMarginPct | contractual_margin |
| payments | PostingReference | posting_id |
| payments | loan_ref | loan_id |
| payments | payment_period | period |
| payments | amount_received | received_amount |
| payments | payment_method | payment_method |
| investor | Loan_ID | loan_id |
| investor | ReportMonth | period |
| investor | ReportedCash | reported_amount |
| investor | ChargedMarginPct | charged_margin |

The JSON files are review aids, not uploads. mapping.json records these choices. expected.json records hand-authored expected outcomes and CSV hashes. The application receives only CSV data and must leave its fixture score unavailable for uploads. No answer key is given to the engine.
