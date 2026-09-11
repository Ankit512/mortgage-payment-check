"""Read-only question routing over one confirmed run.

The model selects a topic, never amounts, citations, accounts or answer prose.
Answers use the same validated summary shown in the dashboard. No write tools.
"""

import re
from decimal import Decimal
from pathlib import Path

from app.engine import load_mapped
from app.validators import injection_scan, pii_scan

CURRENCIES = {"GBP": "£", "EUR": "€", "USD": "$"}
SUGGESTIONS = ["Summarise these payments", "Why is there a shortfall?",
               "Explain the rate margins", "What should I review next?"]


def question_allowed(question):
    return injection_scan([question])[0] == 1 and pii_scan([question])[0] == 1


def answer(snapshot, paths, topic, *, account_id=None, currency="GBP"):
    summary = snapshot["payment_summary"]
    accounts = summary["accounts"]
    if account_id:
        accounts = [a for a in accounts if a["loan_id"] == account_id]
        if not accounts:
            raise ValueError("Choose an account from this check.")
    ids = {a["loan_id"] for a in accounts}
    scoped = accounts[0] if account_id else summary
    findings = [e for e in snapshot["engine_exceptions"] if e["loan_id"] in ids]
    money = lambda value: "—" if value is None else f"{CURRENCIES[currency]}{Decimal(value):,.2f}"
    blocks = []
    def add(heading, text):
        blocks.append({"heading": heading, "text": text})

    if topic == "out_of_scope":
        add("Ask about this payment check", "I can explain payment amounts, repeated-debit patterns, rate margins and the records to review. I cannot recommend a mortgage, predict future payments, move money or change records.")
    elif topic == "help":
        add("Start with the overview", "Choose an example or upload three sample CSVs, confirm the file labels, then compare Payment due with Payment recorded. Select an account to focus both the charts and this conversation. Open See details to inspect original records.")
    elif topic == "summary":
        add("Your payment picture", f"For {scoped['period']}, {money(scoped['scheduled'])} was due and {money(scoped['received'])} was recorded across {len(accounts)} account(s). {len(findings)} item(s) need review under the three checks.")
        add("Differences between accounts", f"Shortfalls total {money(scoped['shortfall'])}; excess receipts total {money(scoped['excess'])}. Extra money on one account does not settle a shortfall on another.")
    elif topic in ("shortfall", "excess"):
        field = "shortfall" if topic == "shortfall" else "excess"
        affected = [a for a in accounts if Decimal(a[field]) > 0]
        add("Less received than due" if topic == "shortfall" else "More received than due",
            f"The {field} totals {money(scoped[field])} across {len(affected)} account(s). This adds each account's difference separately, so unrelated differences do not cancel.")
        for a in affected[:6]:
            add(a["loan_id"], f"Due {money(a['scheduled'])}; recorded {money(a['received'])}; {field} {money(a[field])}.")
        if topic == "excess":
            add("What it means", "Extra receipts alone do not prove a duplicate. The repeated-debit check also checks the number, method and exact payment multiple. These files cannot establish authorisation.")
        if len(affected) > 6:
            add("More accounts", f"Showing 6 of {len(affected)} affected accounts. Use the account selector to inspect another.")
    elif topic in ("missing", "duplicate", "margin", "next_steps"):
        ex_type = {"missing": "MISSING_PAYMENT", "duplicate": "DUPLICATE_DIRECT_DEBIT", "margin": "RATE_MARGIN_BREACH"}.get(topic)
        chosen = [e for e in findings if not ex_type or e["ex_type"] == ex_type]
        if not chosen:
            add("No matching finding", "This check found no item of this type for the selected accounts. That does not rule out other payment differences; compare the due and recorded amounts above.")
        by_id = {a["loan_id"]: a for a in accounts}
        for e in chosen[:6]:
            a = by_id[e["loan_id"]]
            if e["ex_type"] == "MISSING_PAYMENT":
                reason = "No payment entry was found." if not a["posting_count"] else "The payment entries net to zero after reversals."
                text = f"Due {money(a['scheduled'])}; recorded {money(a['received'])}. {reason} Compare the payment record with the schedule for this account and month. Later payments may not be in these files."
            elif e["ex_type"] == "DUPLICATE_DIRECT_DEBIT":
                text = f"{a['direct_debit_count']} direct-debit entries total {money(a['direct_debit_total'])}, against {money(a['scheduled'])} due. Check the references and whether each collection was intended; the files cannot establish authorisation."
            else:
                text = f"Agreed margin {a['contractual_margin']}%; recorded margin {a['charged_margin']}%. Compare the lender report with the agreement. A margin is part of a rate, not the full interest rate or APR. These files do not establish a monetary overcharge."
            add(a["loan_id"], text)
        if len(chosen) > 6:
            add("More items", f"Showing 6 of {len(chosen)} matching findings. Choose one account for a focused explanation.")
        if topic == "margin":
            checked = sum(a["charged_margin"] is not None for a in accounts)
            add("Rate coverage", f"Margins could be compared for {checked} of {len(accounts)} selected accounts. Payment amounts matching does not establish that the margin is correct.")
    elif topic == "sources":
        add("Three records behind this answer", "The payment schedule provides the amount due and agreed margin. The payment record provides posted receipts, including reversals. The lender report provides reported cash and the recorded margin. Source references below use original CSV line numbers.")
    else:
        raise ValueError("Unsupported question topic")

    citations = []
    if topic not in ("help", "out_of_scope"):
        if snapshot["mapping_issues"]:
            add("Some checks were skipped", "The file mapping is incomplete. These figures only describe the available comparisons and are not an all-clear.")
        for kind, path in paths.items():
            table = load_mapped(path, snapshot["confirmed_mapping"][kind], kind=kind)
            rows = [row.source["row_number"] for row in table.rows if row.values.get("loan_id") in ids]
            citations.append({"file": Path(path).name, "rows": rows})
    return {"topic": topic, "blocks": blocks, "citations": citations,
            "run_id": snapshot["run_id"], "account_id": account_id,
            "period": scoped["period"], "currency": currency,
            "currency_note": f"{currency} is a display label; no conversion is applied.",
            "read_only": True, "suggestions": SUGGESTIONS,
            "finding_ids": [e["ex_id"] for e in findings[:6]] if citations else []}


def explicit_account(question, account_ids, selected=None):
    """Do not silently answer a named account using someone else's figures."""
    mentioned = set(re.findall(r"\bSYN-[A-Z0-9-]+", question, re.I))
    lookup = {value.casefold(): value for value in account_ids}
    if any(value.casefold() not in lookup for value in mentioned):
        raise ValueError("That sample account is not in this check. Choose an account from the dashboard.")
    matches = {value for value in account_ids if re.search(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", question, re.I)}
    if len(matches) > 1 or (selected and matches and matches != {selected}):
        raise ValueError("Choose one account in the dashboard, then ask about that account.")
    return next(iter(matches)) if matches else selected
