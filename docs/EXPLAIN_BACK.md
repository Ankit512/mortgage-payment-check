# Owner explain-back log

This file records the PRD section 9 comprehension gates. Answers must come from
the owner; an agent may record them faithfully but must not answer on the owner's
behalf. Each gate is completed before the next implementation milestone begins.

## M1: Synthetic sample generator and answer key

**Build status:** implemented; all 8 tests pass.
**Commit subject:** `feat: add reproducible UC1 sample data and answer key`.
**Comprehension gate:** awaiting the owner's three answers. M2 has not started.

### What this piece does

It creates a small, invented monthly loan book in three differently shaped CSVs:
what should be paid (servicing), what was paid (payments), and what the investor
report says about cash and charged margin. It deliberately inserts missing
payments, duplicate direct debits, and margins above the contract, and records
those edits in a separate answer key. Seed 42 with 40 loans creates four of each
error and 28 clean loans. This gives the later engine something independently
checkable to find. It makes no LLM calls and needs no credentials.

### Three choices and why

1. **Repeatable inputs and exact amounts.** A private seeded random generator,
   a fixed month, and integer cents/basis points avoid moving dates and rounding
   differences. Realistic calendar and interest calculations would add scope
   without helping test these three detectors.
2. **Record errors when inserting them.** The generator writes the answer key
   from its deliberate edits. Asking the engine to create its own answer key
   would let a detector bug appear correct. Tests separately inspect the CSVs.
3. **Different headers, simple cases.** Header names vary to make mapping real,
   while each affected loan gets only one error so the first demo is easy to
   explain by hand. Partial payments and reversals belong in later engine tests.

### Verification

`python3 -m unittest discover tests -v` passed all 8 tests on Python 3.13.3.
The checks cover byte-identical regeneration and checked-in fixtures, different
seeds, isolation from global random state, independent CSV audits across five
seed/count combinations (including N = 1 and N = 2), headers and PII patterns,
invalid counts, and a CLI run with an empty environment from another directory.

The seed-42 fixture has 40 servicing rows, 40 payment postings, 40 investor rows
and 12 manifest entries. The equal payment-row count is coincidental: four
missing payments remove four rows and four duplicate debits add four rows.
Counts alone therefore cannot detect these errors.

Source-row inspection also confirmed these representative examples:

- `SYN-L000005`: scheduled 2580.61, no payment postings, investor cash 0.00.
- `SYN-L000011`: scheduled 1259.90, two postings of 1259.90, investor cash 2519.80.
- `SYN-L000013`: contractual margin 2.00%, charged margin 2.59%, difference
  0.59 percentage points; its normal payment is 2121.27.

Numerical engine scoring, validators, the API and Disseqt transport are not
implemented or claimed in this milestone.

### Questions for the owner

1. If generating seed 42 twice gives identical files, what does that prove, and
   what extra check is needed to know the seeded answer key is correct?
2. For `SYN-L000005` and `SYN-L000011`, what rows or missing rows across the three
   CSVs prove a missing payment and a duplicate debit, respectively? Why would
   simply comparing total file row counts miss these errors?
3. Why do the three files use different loan-ID and amount headers? In the later
   pipeline, what may the LLM propose, who approves it, and who does the maths?

### Owner answers

1. Pending.
2. Pending.
3. Pending.

**Review outcome:** pending. Do not dispatch M2 until the owner has answered and
any misunderstandings have been clarified.
