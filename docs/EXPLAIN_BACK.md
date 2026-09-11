# Owner explain-back log

This file records the PRD section 9 comprehension gates. Answers must come from
the owner; an agent may record them faithfully but must not answer on the owner's
behalf. Each gate is completed before the next implementation milestone begins.

## M1: Synthetic sample generator and answer key

**Build status:** implemented; all 8 tests pass.
**Commit subject:** `feat: add reproducible UC1 sample data and answer key`.
**Comprehension gate:** initial answers received on 2026-09-11; reviewer
clarifications pending. M2 has not started.

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

Received on 2026-09-11, preserved verbatim below. Reviewer corrections are kept
separate; they are not treated as revised owner answers.

**A1.** Byte-identical regeneration proves the generator is repeatable: same seed, same files, so any reviewer or CI run reproduces my exact test conditions. It proves nothing about correctness — a buggy generator produces the same wrong files every time. Correctness is covered separately, by independently verifying the manifest's entries against the CSVs. And there's a limit worth naming: since the generator writes the answer key the engine will be graded against, the ground-truth test validates that generator and engine agree about the seeded errors — it proves the mechanism works, not real-world detection performance. It also doesn't prove coverage: a seed could happen to plant zero instances of one error type, leaving that detection branch unexercised.

**A2.** A missing payment shows as a scheduled amount in the servicing extract with zero corresponding rows in the payments file; a duplicate debit shows as two identical payment rows where servicing scheduled one. The investor report corroborates both — 0 collected for the first, 2× for the second. Total row counts miss both because the errors cancel: one loan short a row plus another loan with an extra row leaves the count unchanged — and the amounts cancel the same way, so even total-value reconciliation misses them. That's why the engine matches per loan, never at file level.

**A3.** Headers differ across the files because real systems never agree on naming — identical headers would make mapping trivially fake and the human checkpoint pointless. The LLM proposes the header-to-canonical mapping, because generalizing over unseen header patterns is the one task in this pipeline it's genuinely best at — a deterministic alias table only knows headers it's already seen (our mock provider is exactly that, which is why it's the fallback, not the design). A human approves or corrects the mapping before anything runs, because a wrong mapping silently poisons every downstream number. The deterministic engine then performs all arithmetic on the mapped data. Propose, approve, compute — three roles, deliberately separated, and that separation is the whole design.

### Reviewer assessment

The separation of reproducibility from correctness, the need for per-loan
reconciliation, and the propose/approve/compute boundary are understood. Several
claims need correction before these answers are used in an interview:

1. **Coverage is guaranteed by the current generator for N >= 3.** It cycles
   through the three exception types after selecting affected loans. A seed
   changes the affected loans and amounts, not whether a type is represented.
   At N = 40 there are four of each type; N = 1 or 2 intentionally covers fewer.
   The remaining limitation is scenario coverage within each type: partial
   payments, reversals, multiple months, malformed values and overlapping errors
   are absent. Future engine tests should include independently constructed
   examples with explicit expected results. No engine has been built or scored
   at M1, so engine/manifest agreement is a future acceptance check.
2. **The duplicate payment rows are not identical.** They have distinct posting
   IDs and matching loan, period, method and amount. Missing payments have no
   rows in these fixtures, whereas the PRD's engine rule is a positive scheduled
   amount and zero net received. Multiple postings alone are insufficient to
   establish a duplicate: two 500.00 instalments against 1000.00 scheduled are
   a useful proposed negative test. Matching must account for loan and reporting
   period, even though these fixtures contain only one month.
3. **Row-count cancellation does not imply monetary cancellation.** Missing
   amounts and excess duplicate amounts must sum to the same value for that to
   happen. Aggregate controls can detect net differences, but cannot reliably
   establish which loans are wrong or establish correctness when totals agree.
   The generator derives investor cash from the payment postings, so agreement
   between those two files demonstrates fixture consistency, not independence
   between real-world source systems.

   Direct Decimal sums of the checked-in seed-42 CSVs show:

   | Measure | Amount |
   | --- | ---: |
   | Servicing scheduled total | 66,561.34 |
   | Payments received total | 67,053.18 |
   | Investor reported cash total | 67,053.18 |
   | Missing-payment shortage | 7,430.01 |
   | Extra duplicate payments | 7,921.85 |
   | Received minus scheduled | +491.84 |

   All three files have 40 data rows. Scheduled-versus-received totals expose
   a net discrepancy here, while payments-versus-investor totals still agree.

4. **Mapping uses meaning as well as spelling.** Different headers make the demo
   realistic, but even matching names can hide different meanings or units (for
   example, scheduled versus received amount, or 2.50 versus 0.025 for a rate).
   A human checkpoint is still useful with identical headers. Semantic reasoning
   is a reason to try an LLM for mapping, not evidence that it is best at that
   task. The PRD also assigns it constrained classification and rationale
   drafting. The alias-table mock is the deliberate default for keyless runs,
   not an automatic recovery mechanism when OpenAI fails. Human confirmation
   establishes an approval event, not proof of a correct mapping; deterministic
   code makes arithmetic repeatable but cannot repair incorrect inputs by itself.

### Follow-up round

These questions address only the unsettled parts of the M1 explanations. The
recommendations are the reviewer's positions, not the owner's answers.

1. **Coverage:** If the future engine detects all seed-42 exceptions correctly,
   what remains untested before claiming broader detection quality?
   Recommended position: the seeded cases pass under their stated assumptions;
   add hand-authored boundary and negative cases with independent expectations,
   and retain the limitation that this is not measured real-world performance.
2. **Duplicate semantics:** A loan is scheduled to pay 1000.00 and has two
   distinct direct-debit postings of 500.00 each in the same period. Should it
   be flagged as a duplicate, and why?
   Recommended position: no; those postings sum to one scheduled payment.
   This exposes an ambiguity in R2's phrase "exact multiple": clarify that the
   duplicate detector requires a multiple of at least two, alongside its other
   checks. This is a proposed clarification, not an implemented engine rule.
3. **Approval boundary:** A human approves a mapping that swaps two numeric
   amount fields. What does the approval event prove, and what does it leave
   unproven?
   Recommended position: the checkpoint was honoured, but semantic correctness
   is unproven. Arithmetic can be exact on wrongly interpreted data. Structural
   mapping checks and independent scoring of deliberately wrong mappings should
   expose issues in the PoC; a production run would not have this synthetic
   answer key, and these checks cannot guarantee every semantic error is caught.

**Owner follow-up:** pending.

**Review outcome:** clarification requested. Preserve the original answers and
record the owner's follow-up separately before closing the M1 gate. M2 remains
unstarted under PRD section 9.
