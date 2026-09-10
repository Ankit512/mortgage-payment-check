"""Generate three synthetic monthly files and an independently seeded answer key.

Run from the repository root:
    python3 data/generate_samples.py --seed 42 --n-loans 40
"""

import argparse
import csv
import json
import random
from pathlib import Path


EXCEPTION_TYPES = (
    "MISSING_PAYMENT",
    "DUPLICATE_DIRECT_DEBIT",
    "RATE_MARGIN_BREACH",
)
PERIOD = "2026-08"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "samples"
HEADERS = {
    "servicing_extract.csv": (
        "LoanIdentifier", "Period", "ScheduledInstalment", "ContractMarginPct",
    ),
    "payments_file.csv": (
        "PostingReference", "loan_ref", "payment_period", "amount_received",
        "payment_method",
    ),
    "investor_report.csv": (
        "Loan_ID", "ReportMonth", "ReportedCash", "ChargedMarginPct",
    ),
}


def _hundredths(value: int) -> str:
    """Render integer cents, or basis points expressed as a percentage."""
    return f"{value // 100}.{value % 100:02d}"


def generate_samples(
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    *,
    seed: int = 42,
    n_loans: int = 40,
) -> dict:
    """Write fixed-period fixtures; the same seed and count reproduce every byte.

    Each affected loan gets one error. At 40 loans, four of each type are seeded.
    For one or two loans, only the first one or two types can be represented.
    The manifest is recorded when an error is inserted, never inferred by an
    engine. This module has no dependency on the future reconciliation engine.
    """
    if isinstance(n_loans, bool) or not isinstance(n_loans, int) or n_loans < 1:
        raise ValueError("n_loans must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    rng = random.Random(seed)
    loans = [
        {
            "loan_id": f"SYN-L{index:06d}",
            "scheduled_cents": rng.randint(65_000, 260_000),
            "contract_bps": rng.randint(150, 350),
        }
        for index in range(1, n_loans + 1)
    ]
    affected_count = min(n_loans, 3 * max(1, n_loans // 10))
    selected = rng.sample(range(n_loans), affected_count)
    error_by_index = {
        index: EXCEPTION_TYPES[position % len(EXCEPTION_TYPES)]
        for position, index in enumerate(selected)
    }

    files: dict[str, list[dict[str, str]]] = {name: [] for name in HEADERS}
    seeded_exceptions = []
    for index, loan in enumerate(loans):
        loan_id = loan["loan_id"]
        scheduled = loan["scheduled_cents"]
        contract = loan["contract_bps"]
        error = error_by_index.get(index)
        posting_count = 1
        charged = contract
        if error == "MISSING_PAYMENT":
            posting_count = 0
        elif error == "DUPLICATE_DIRECT_DEBIT":
            posting_count = 2
        elif error == "RATE_MARGIN_BREACH":
            charged += rng.randint(25, 100)

        received = scheduled * posting_count
        files["servicing_extract.csv"].append({
            "LoanIdentifier": loan_id,
            "Period": PERIOD,
            "ScheduledInstalment": _hundredths(scheduled),
            "ContractMarginPct": _hundredths(contract),
        })
        for posting in range(posting_count):
            files["payments_file.csv"].append({
                "PostingReference": f"SYN-P{index + 1:06d}-{'AB'[posting]}",
                "loan_ref": loan_id,
                "payment_period": PERIOD,
                "amount_received": _hundredths(scheduled),
                "payment_method": "DIRECT_DEBIT",
            })
        files["investor_report.csv"].append({
            "Loan_ID": loan_id,
            "ReportMonth": PERIOD,
            "ReportedCash": _hundredths(received),
            "ChargedMarginPct": _hundredths(charged),
        })

        if error == "MISSING_PAYMENT":
            detail = (
                f"Loan {loan_id}: scheduled {_hundredths(scheduled)} for {PERIOD}; "
                "received 0.00; no payment postings."
            )
        elif error == "DUPLICATE_DIRECT_DEBIT":
            detail = (
                f"Loan {loan_id}: 2 direct-debit postings of {_hundredths(scheduled)} "
                f"for {PERIOD}; received {_hundredths(received)}, "
                f"exactly 2 times the scheduled {_hundredths(scheduled)}."
            )
        elif error == "RATE_MARGIN_BREACH":
            detail = (
                f"Loan {loan_id}: charged margin {_hundredths(charged)}% "
                f"exceeds contractual margin {_hundredths(contract)}% "
                f"by {_hundredths(charged - contract)} percentage points for {PERIOD}."
            )
        if error is not None:
            seeded_exceptions.append({"type": error, "loan_id": loan_id, "detail": detail})

    manifest = {
        "seed": seed,
        "n_loans": n_loans,
        "seeded_exceptions": seeded_exceptions,
        "exception_count": len(seeded_exceptions),
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, rows in files.items():
        with (output_dir / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=HEADERS[filename], lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (output_dir / "ground_truth.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-loans", type=int, default=40)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    if args.n_loans < 1:
        parser.error("--n-loans must be a positive integer")
    manifest = generate_samples(args.output_dir, seed=args.seed, n_loans=args.n_loans)
    print(
        f"Wrote 3 synthetic CSVs and ground_truth.json to {args.output_dir}: "
        f"{manifest['n_loans']} loans, {manifest['exception_count']} seeded exceptions "
        f"(seed {manifest['seed']})."
    )


if __name__ == "__main__":
    main()
