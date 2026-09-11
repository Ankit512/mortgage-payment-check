# Mortgage file examples

Six small, manually authored examples let you try uploading files and compare the results with a known outcome. All records are invented and contain no real customer details. These packs are independent of the seed-based M1 generator.

| Example | Accounts | Expected issues | What to notice |
| --- | ---: | ---: | --- |
| [Everything matches](all_clear/README.md) | 4 | 0 | 0 issues. Expected and received: 3,050.50. The split payment is normal. |
| [A payment is missing](missing_payment/README.md) | 3 | 1 | 1 issue on 1 account. Received money is 1,500.00 below the amount due. |
| [A payment may have been taken twice](duplicate_payment/README.md) | 3 | 1 | 1 issue on 1 account. Received money is 1,200.00 above the amount due. |
| [A mortgage margin needs checking](margin_mismatch/README.md) | 3 | 1 | 1 issue on 1 account. Payments match at 3,450.00; one margin is 0.25 percentage points above the agreement. |
| [Several things need checking](mixed_checks/README.md) | 6 | 5 | 5 issues on 3 accounts. Shortfalls total 1,900.00 and extra receipts total 800.00; the overall difference is -1,100.00. |
| [Different file headings](unfamiliar_headers/README.md) | 5 | 3 | After matching columns: 3 issues on 3 accounts. Shortfalls are 1,050.00 and extra receipts are 2,049.99. |

Each folder contains the same three upload filenames: servicing_extract.csv (amounts due and agreed margins), payments_file.csv (individual money entries), and investor_report.csv (cash and applied margins reported onward). A row in the payments file is an entry, so one account may have several rows.

Use each folder's guide to review the column mapping and expected totals. Never mix files from different folders in one upload. All examples cover August 2026. CSV amounts have no specified currency; margin values are percentages written as numbers, so 2.00 means 2.00%. A difference between two margins is measured in percentage points.

Run the independent upload verification from the repository root:

```sh
.venv/bin/python -m scripts.check_scenarios
```

The harness uploads each pack twice through FastAPI and the real LangGraph checkpoint with the mock provider. It confirms the supplied mapping as an automated test, checks account arithmetic independently with Decimal, compares the dashboard's account figures, totals and chart counts against the expected results, compares exact issue identities and evidence, and verifies repeated outcomes. It does not measure Qwen quality or authenticate to Disseqt. Uploaded files have no in-app ground-truth score: expected.json is only the external test oracle.

The mixed example includes overlapping issues, a reversed payment and normal split payments. The unfamiliar-headings example makes a useful manual mapping exercise and shows an excess receipt that does not meet the duplicate rule. None of the packs proves coverage beyond the explicitly exercised cases.
