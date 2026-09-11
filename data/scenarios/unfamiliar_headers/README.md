# Different file headings

Five accounts using unfamiliar column names. Match the columns before running the payment and margin checks.

After matching columns: 3 issues on 3 accounts. Shortfalls are 1,050.00 and extra receipts are 2,049.99.

These are invented mortgage records for August 2026. Amounts have two decimal places. No currency is specified by the CSV contract.

## Try this example

1. Start a new file check and choose the upload option.
2. Upload all three CSVs from this folder into their matching file slots.
3. Review the column choices below, approve them yourself, then run the checks.
4. Compare the result with the expected outcome. Upload the same files again to check that the numerical results repeat.

Use the mock provider for a quick deterministic walkthrough. It does not test the quality of Qwen's wording.

## Expected outcome

- The mock provider has no aliases for these headings. Use the mapping table below to make the column choices yourself. Qwen may propose matches, but its proposal still needs your review.
- SYN-L000604 receives 1,999.99 against 1,000.00 due. The dashboard should show 999.99 above the amount due. The current duplicate rule requires an exact multiple of at least twice the due amount, so this account has no duplicate flag.
- SYN-L000603 has a margin difference of just 0.01 percentage points. The margin rule still flags it.

| Measure | Expected |
| --- | ---: |
| Accounts | 5 |
| Issues | 3 |
| Accounts with an issue | 3 |
| Amount due | 5095.50 |
| Net money received | 6095.49 |
| Investor-reported cash | 6095.49 |
| Received minus due | 999.99 |
| Total account shortfalls | 1050.00 |
| Total account excess receipts | 2049.99 |

Shortfall and excess are calculated separately for each account before adding them up. An issue count covers the three implemented checks; it is not proof that every possible mortgage error was checked.

## Column choices

| File | CSV heading | Choose this field |
| --- | --- | --- |
| servicing | Mortgage reference | loan_id |
| servicing | Statement cycle | period |
| servicing | Instalment due this cycle | scheduled_amount |
| servicing | Agreed margin percent | contractual_margin |
| payments | Collection entry | posting_id |
| payments | Agreement reference | loan_id |
| payments | Collection cycle | period |
| payments | Net amount posted | received_amount |
| payments | Collection route | payment_method |
| investor | Facility reference | loan_id |
| investor | Cash reporting cycle | period |
| investor | Cash credited to investor | reported_amount |
| investor | Applied margin percent | charged_margin |

The JSON files are review aids, not uploads. mapping.json records these choices. expected.json records hand-authored expected outcomes and CSV hashes. The application receives only CSV data and must leave its fixture score unavailable for uploads. No answer key is given to the engine.
