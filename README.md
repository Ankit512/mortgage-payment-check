# Disseqt UC1: Reconciliation and Anomaly Detection

Interview PoC for Mortgage Capital's **use case 1**. The implementation follows
the supplied [PRD](docs/PRD.md) in serial milestones, each followed by the owner's
explain-back gate. Only **M1: synthetic sample data** is implemented so far.

## Run M1 without credentials

Python 3.10 or newer; this milestone uses only the standard library.

```bash
python3 data/generate_samples.py --seed 42 --n-loans 40
python3 -m unittest discover tests -v
```

The generator writes three CSVs and `ground_truth.json` to `data/samples/`.
Use `--output-dir /path/to/samples` to choose a different directory. Regeneration
replaces those four files. Seed 42 with 40 loans produces 12 exceptions: four
missing payments, four duplicate direct debits, and four rate-margin breaches.
All records are synthetic. No account or service is contacted.

## Intended architecture

```text
synthetic CSVs [M1] --> ingest + scans --> propose mapping (LLM)
                                               |
                                      HUMAN CONFIRMS MAPPING
                                               |
                                      reconcile (code only)
                                               |
                                     classify + draft (LLM)
                                               |
                                      validators + policy
                                       /               \
                                  PASS                  BLOCK
                             remediation log        held for review

Every step --> Disseqt wire client --> local JSONL / live transport
```

Everything after CSV generation remains to be built. No engine, API, LLM call,
validator verdict, trace, or live Disseqt result is claimed by this milestone.

## Data and decisions

- A private random generator, fixed reporting month, stable row ordering and
  explicit formatting make identical seed/count inputs produce identical bytes.
- Amounts are generated in integer cents; margins in integer basis points and
  exported as percentages. This avoids binary floating-point rounding in fixtures.
- An error is recorded in the answer key when it is inserted. The answer key
  does not call a detector, so the later engine cannot grade itself.
- Raw headers differ across files so human-confirmed mapping has a real job.
  Each affected loan has one exception, making the first demo easy to audit.

See [the sample contract](data/README.md) for columns and manual verification,
[the assignment review](docs/ASSIGNMENT_REVIEW.md) for requirements and gaps, and
[EXPLAIN_BACK](docs/EXPLAIN_BACK.md) for milestone briefs and owner answers.

## Layout

```text
data/generate_samples.py  Seeded generator and answer-key writer
data/samples/             Checked-in seed-42 fixture set
tests/                   Standard-library unittest suite
docs/PRD.md              Unmodified supplied PRD
docs/ASSIGNMENT_REVIEW.md Assignment comparison and milestone tracker
docs/EXPLAIN_BACK.md      Owner comprehension gates
```
