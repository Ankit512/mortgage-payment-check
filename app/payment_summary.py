"""Consumer-facing figures derived from the engine's validated, mapped rows.

Call after reconcile() succeeds. Money stays in integer minor units until it is
serialized as a decimal string. A portfolio shortfall is summed per account;
excess payments on another account cannot cancel it out. No currency, balance,
APR, or historical trend is inferred from these single-month inputs.
"""

from collections import defaultdict

from app.engine import CANONICAL_FIELDS, _display, _minor_units


def payment_summary(servicing, payments, investor, findings):
    tables = (servicing, payments, investor)
    if any(not table.supports(*CANONICAL_FIELDS[table.kind]) for table in tables):
        return {"available": False, "reason": "Some file columns are unconfirmed. Payment totals are unavailable until all required fields are matched.",
                "currency": None, "accounts": []}

    ledger, reports, types = defaultdict(list), {}, defaultdict(list)
    for row in payments.rows:
        ledger[row.values["loan_id"]].append(row)
    for row in investor.rows:
        reports[row.values["loan_id"]] = row
    for item in findings:
        types[item["loan_id"]].append(item["ex_type"])

    accounts = []
    totals = dict.fromkeys(("scheduled", "received", "shortfall", "excess"), 0)
    cash_counts = dict.fromkeys(("matched", "under", "over"), 0)
    period = None
    reported_total = 0
    for row in sorted(servicing.rows, key=lambda row: row.values["loan_id"]):
        values = row.values
        loan_id, period = values["loan_id"], values["period"]
        postings = ledger[loan_id]
        report = reports.get(loan_id)
        due = _minor_units(values["scheduled_amount"])
        paid = sum(_minor_units(item.values["received_amount"]) for item in postings)
        shortfall, excess = max(0, due - paid), max(0, paid - due)
        cash_status = "under" if shortfall else "over" if excess else "matched"
        cash_counts[cash_status] += 1
        debits = [item for item in postings if item.values["payment_method"] == "DIRECT_DEBIT"]
        reported = _minor_units(report.values["reported_amount"]) if report else None
        if reported is not None:
            reported_total += reported
        for key, value in (("scheduled", due), ("received", paid), ("shortfall", shortfall), ("excess", excess)):
            totals[key] += value
        accounts.append({
            "loan_id": loan_id, "period": period,
            "scheduled": _display(due), "received": _display(paid),
            "shortfall": _display(shortfall), "excess": _display(excess),
            "net_difference": _display(paid - due), "cash_status": cash_status,
            "posting_count": len(postings), "direct_debit_count": len(debits),
            "direct_debit_total": _display(sum(_minor_units(item.values["received_amount"]) for item in debits)),
            "contractual_margin": _display(_minor_units(values["contractual_margin"])),
            "charged_margin": _display(_minor_units(report.values["charged_margin"])) if report else None,
            "reported": _display(reported) if reported is not None else None,
            "issue_types": types[loan_id],
        })

    return {
        "available": True, "currency": None, "period": period, "accounts": accounts,
        **{key: _display(value) for key, value in totals.items()},
        "net_difference": _display(totals["received"] - totals["scheduled"]),
        # A missing investor row is missing data, not reported zero cash.
        "reported": _display(reported_total) if len(reports) == len(accounts) else None,
        "cash_counts": cash_counts, "account_count": len(accounts),
        "accounts_with_findings": sum(bool(account["issue_types"]) for account in accounts),
        "margin_checked_accounts": len(reports),
        "issue_counts": {kind: sum(kind in account["issue_types"] for account in accounts)
                         for kind in ("MISSING_PAYMENT", "DUPLICATE_DIRECT_DEBIT", "RATE_MARGIN_BREACH")},
    }
