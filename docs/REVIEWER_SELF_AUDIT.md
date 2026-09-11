# Stress test of the M1 reviewer's assumptions

2026-09-11. Requested by the owner to challenge the assistant's own suggestions.
Scope: the previous review of A1-A3, the M1 generator and tests, and the relevant
PRD requirements. This was not an evaluation of a built reconciliation engine;
M2 had not started when this audit was performed; the later handoff is recorded
in the addendum below.

An independent worker challenged the review while the primary agent tested
the suite's resistance to incorrect manifest descriptions. All adversarial
generator edits and additional sample sets were confined to temporary copies.

## Verdict

The numerical and coverage corrections hold. The reviewer's proposed duplicate
rule needed a narrower claim; the rate-unit example exceeded what the stated
mapping interface could infer. The reviewer also imposed an extra mandatory
question round that the PRD does not explicitly require. The existing generator
has not been shown to produce incorrect seed-42 records, but the tests had a
demonstrated blind spot in manifest descriptions. That check is now strengthened.

## Evidence and corrections

| Previous claim / implication | Audit result | Proportionate action |
| --- | --- | --- |
| All three types are guaranteed for N >= 3. | Supported by the count formula and cyclic assignment in `data/generate_samples.py`; worker also checked 2,000 combinations: N = 1 through 100, seeds 0 through 19. | Retain. Distinguish exception-type coverage from behavioural coverage. |
| Seed-42 row counts cancel, but monetary differences do not. | Independently recomputed with Decimal: scheduled 66,561.34, received/reported 67,053.18, difference +491.84. All CSVs have 40 data rows. | Retain. Aggregate checks are useful but cannot identify every wrong loan. |
| Investor cash is not independent verification of payment cash. | Both derive from the same scheduled amount and posting count. | Retain this limitation. Calling the investor rows corroborating fixture evidence is reasonable; claiming independent source assurance is not. |
| Requiring a duplicate multiple >= 2 solves the duplicate question. | It excludes one-times and zero-times totals, but cannot establish whether a payment was authorised or accidental. | Retain as a proposed clarification of the PoC rule; do not present it as a universal duplicate detector. |
| Period handling requires matching on loan plus period. | This works, but is stronger than needed for a deliberately single-month fixture. | Either validate that all inputs have the same month or explicitly include period in matching. No general multi-month subsystem is required. |
| Human mapping review should catch identical names with different rate units. | This is a legitimate risk, but `propose_mapping(headers, canonical)` does not receive values or unit metadata. | Use the documented fixture units and explain the limit. Do not promise the LLM infers information it does not receive. |
| The owner meant automatic failover by calling mock a fallback. | That intent was inferred, not established. A manually selected alternative is also a natural meaning of fallback. | Clarify mode behaviour without attributing the stronger claim to the owner. Mock is the PRD's explicit default; real-provider failure must be reported honestly. |
| Passing M1 tests independently validates the whole answer key. | Exception identities and CSV relationships are checked; numerical claims in `detail` originally were not. A mutation survived all eight tests after fixture regeneration. | Add a focused check against raw CSV values and verify it rejects mutated descriptions. Completed in this audit. |
| PRD section 9 explicitly requires the extra three answers. | It requires the original three answers, which the owner supplied. Meaningful review is required; an additional compulsory round was the reviewer's interpretation. | Withdraw the extra mandatory quiz as a blocker. Record corrections without claiming the owner has accepted wording they have not supplied. |

## Duplicate-rule counterexamples

The worker evaluated two small Decimal predicates, not production code. The
literal reading of R2 was more than one posting with a net total exactly
divisible by a positive scheduled amount. The proposed clarification also
requires a net total of at least twice that amount. Scheduled amount = 1000:

| Postings | Literal R2 reading | With multiple >= 2 |
| --- | --- | --- |
| 500 + 500 | Flags | Does not flag |
| 1000 - 1000 | Flags | Does not flag |
| 1000 + 1000 - 1000 | Flags | Does not flag |
| 1500 + 500 | Flags | Flags |
| 1000 + 1000 + 10 | Does not flag | Does not flag |

The first three support the clarification. The last two show why the rule must
remain scoped: exact net multiples do not establish duplicated transactions,
and a plausible extra posting can break the exact-multiple condition.

Even two distinct direct-debit postings of 1000 have two possible histories:
an accidental second collection or an authorised additional payment. The CSVs
contain no authorisation field to distinguish those histories. The synthetic
manifest tells us which loans were deliberately given the duplicate pattern;
it does not make that missing information available for arbitrary real inputs.

For M2, implement and test the stated numerical pattern with the clarified
positive threshold and payment-method handling. Explain it as a candidate
exception under the fixture's assumptions. Do not add bank settlement,
authorisation, partial-allocation or currency-conversion infrastructure to M1.
These are reviewer recommendations; no M2 rule has been implemented here.

## Manifest-description mutation experiment

The primary agent copied `data/` and `tests/` into a temporary directory and
replaced the missing-payment description's scheduled amount with `999999.99`.
No CSV amounts or exception identities were changed.

1. With the original checked-in fixtures retained, the old suite failed two
   byte-comparison checks. This shows that the snapshots do guard against drift.
2. After regenerating the fixtures with the mutated generator, as the README
   quickstart does, all eight old tests passed. The description for `SYN-L000005`
   falsely claimed a scheduled amount of 999999.99 while its source CSV still
   contained 2580.61.
3. The worker independently reproduced the same weakness with a rate-breach
   description claiming a difference of 99999.99 percentage points.

This does not demonstrate a wrong number in the current generator output. It
demonstrates that regenerating the snapshot can legitimise an incorrect new
description unless the suite checks that description against source facts.

The new test, `test_manifest_details_quote_actual_source_amounts_and_margins`,
reads the exported CSVs and compares described scheduled amounts, received
amounts, posting counts, posting amounts, multiples, margins and margin
differences with source values and Decimal calculations. It covers three
seed/count configurations with all exception types present.

Validation after the change:

- `python3 -m unittest discover tests -v`: all nine tests pass.
- False scheduled amount, false received amount and false margin difference
  were each reintroduced separately in temporary copies, followed by fixture
  regeneration. Each caused the new test to fail on 15 subcases.
- The working generator and checked-in CSVs/manifest were not changed.

This is a check of the generator's known description format, not a general
semantic-faithfulness validator. It does not replace R4 or prove that an LLM's
arbitrary prose will be safe.

## Practical scope and remaining limits

M1 is a credible, small synthetic data generator. It does not need production
data or a broad LLM mapping benchmark to fulfil its acceptance criteria. Exact
regeneration is supported for the tested generator, inputs and Python 3.13.3
environment; this audit does not certify every Python/runtime combination.

The next implementation milestone should focus on the three deterministic
detectors, manually constructed negative/boundary cases, source evidence, and
the PRD's deliberately wrong-mapping score check. The later structural human
checkpoint and live instrumentation remain separate requirements. Extra review
questions, large edge-case frameworks and claims of real-world accuracy would
not substitute for delivering those requirements.

The original three owner answers remain verbatim in `EXPLAIN_BACK.md`. The
reviewer has withdrawn the additional mandatory round. No owner agreement with
the reviewer's revised wording has been invented, and this self-audit request
has not been treated as authorisation to silently resolve new domain policy.

## Owner-supplied independent second pass

After this audit, the owner supplied a second-pass Grok report against `ba7c5fa`
and directed the builder to continue into M2. Hydroid matched that commit when
the handoff was received. The report confirmed the totals, representative loans,
coverage guarantee, derived investor cash and the numerical-slot mutation catches.
It also confirmed that the first-match checks still permit extra later numbers,
reversed relationship wording, changed posting-count claims, extended dates and
wrong exception vocabulary after fixture regeneration. This is consistent with
the stated known-format limitation; it does not reopen M1 or introduce an M1
faithfulness validator. Those cases are retained as later test considerations.

The owner explicitly closed the M1 comprehension gate and kept the extra quiz
withdrawn. The M1 verification-count wording in EXPLAIN_BACK has been corrected
to nine. This addendum records the supplied report, not a claim that the builder
reran every external mutation. M2 implementation and its own measured results
are documented in ENGINE and the next EXPLAIN_BACK entry.
