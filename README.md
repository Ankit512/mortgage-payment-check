# Disseqt UC1: Reconciliation and Anomaly Detection

Interview PoC for Mortgage Capital's **use case 1**. The implementation follows
the supplied [PRD](docs/PRD.md) in serial milestones, each followed by the owner's
explain-back record. **M1: synthetic sample data** and **M2: deterministic
reconciliation and scoring** are implemented.

## Run the implemented milestones without credentials

Python 3.10 or newer; this milestone uses only the standard library.

```bash
python3 data/generate_samples.py --seed 42 --n-loans 40
python3 -m unittest discover tests -v
```

The generator writes three CSVs and `ground_truth.json` to `data/samples/`.
Use `--output-dir /path/to/samples` to choose a different directory. Regeneration
replaces those four files. Seed 42 with 40 loans produces 12 exceptions: four
missing payments, four duplicate direct debits, and four rate-margin breaches.
All records are synthetic. No account or service is contacted. The full suite has
37 tests: 9 for M1 and 28 for M2. The engine finds all 12 seeded exceptions with
precision 1.0, recall 1.0 and zero false positives. An omitted amount mapping
reduces recall to 1/3 with eight missed entries and visible mapping diagnostics.

See [the engine contract and runnable example](docs/ENGINE.md) to invoke
`load_mapped`, `reconcile` and `score_against_ground_truth` directly.

## Intended architecture

```text
synthetic CSVs [M1] --> ingest + scans --> propose mapping (LLM)
                                               |
                                      HUMAN CONFIRMS MAPPING
                                               |
                                      reconcile (code only) [M2]
                                               |
                                     classify + draft (LLM)
                                               |
                                      validators + policy
                                       /               \
                                  PASS                  BLOCK
                             remediation log        held for review

Every step --> Disseqt wire client --> local JSONL / live transport
```

The API, graph checkpoint, LLM provider, validators and Disseqt transport remain
to be built. Calling the M2 engine directly does not demonstrate the future
structural human checkpoint or produce a PASS/BLOCK verdict.

## Data and decisions

- A private random generator, fixed reporting month, stable row ordering and
  explicit formatting make identical seed/count inputs produce identical bytes.
- Amounts are generated in integer cents; margins in integer basis points and
  exported as percentages. This avoids binary floating-point rounding in fixtures.
- An error is recorded in the answer key when it is inserted. The answer key
  does not call a detector, so the later engine cannot grade itself.
- Raw headers differ across files so human-confirmed mapping has a real job.
  Each affected loan has one exception, making the first demo easy to audit.
- The engine uses exact integer cents/basis points and preserves raw source
  records. It validates a single reporting month, records missing mappings, and
  rejects malformed mapped values. It never substitutes a model for arithmetic.
- Duplicate detection is the specified net-multiple pattern (at least 2x). It
  cannot determine authorisation from the available columns. Hand-authored tests
  cover split payments, reversals, overlapping errors and other boundaries.

See [the sample contract](data/README.md) for columns and manual verification,
[the assignment review](docs/ASSIGNMENT_REVIEW.md) for requirements and gaps, and
[EXPLAIN_BACK](docs/EXPLAIN_BACK.md) for milestone briefs and owner answers.

## Layout

```text
data/generate_samples.py  Seeded generator and answer-key writer
data/samples/             Checked-in seed-42 fixture set
app/engine.py             Mapping loader, deterministic detectors and scoring
tests/                   Standard-library unittest suite
docs/ENGINE.md            M2 interface, numerical contract and example
docs/PRD.md              Unmodified supplied PRD
docs/ASSIGNMENT_REVIEW.md Assignment comparison and milestone tracker
docs/EXPLAIN_BACK.md      Owner comprehension gates
```
