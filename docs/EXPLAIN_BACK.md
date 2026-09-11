# Owner explain-back log

This file records the PRD section 9 comprehension gates. Answers must come from
the owner; an agent may record them faithfully but must not answer on the owner's
behalf. Each gate is completed before the next implementation milestone begins.

## M1: Synthetic sample generator and answer key

**Build status:** implemented; 9 tests pass after the reviewer self-audit
strengthened manifest-description checks (the original M1 suite had 8).
**Commit subject:** `feat: add reproducible UC1 sample data and answer key`.
**Comprehension gate:** the three required answers were received and reviewed
on 2026-09-11. The owner explicitly closed M1 in the independent second-pass
handoff and directed implementation of M2. The extra follow-up quiz stays
withdrawn. This does not claim agreement with every revised wording.

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

The completed M1 suite passed all 9 tests on Python 3.13.3 (8 at initial commit,
plus the source-based description check from the self-audit). The current full
command, `python3 -m unittest discover tests -v`, also includes the M2 tests below.
The checks cover byte-identical regeneration and checked-in fixtures, different
seeds, isolation from global random state, independent CSV audits across five
seed/count combinations (including N = 1 and N = 2), headers and PII patterns,
invalid counts, numerical description slots against source values, and a CLI
run with an empty environment from another directory.

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
   a useful proposed negative test. Period consistency matters; validating that
   all files describe the same month is sufficient for this single-month PoC.
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
   drafting. The alias-table mock is the deliberate default for keyless runs.
   If "fallback" meant automatic recovery when OpenAI fails, the PRD does not
   specify that behaviour; the owner's wording did not establish that intent.
   Human confirmation
   establishes an approval event, not proof of a correct mapping; deterministic
   code makes arithmetic repeatable but cannot repair incorrect inputs by itself.

### Proposed follow-up round (optional; mandatory status withdrawn)

These questions were proposed in the first review. The self-audit below withdraws
their status as a mandatory gate. They remain optional interview practice. The
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

**Owner follow-up:** none recorded; no additional mandatory round imposed.

### Reviewer self-audit and revised outcome

At the owner's request, an independent worker challenged the assistant's review
while the assistant ran adversarial tests. See
[REVIEWER_SELF_AUDIT.md](REVIEWER_SELF_AUDIT.md) for evidence and experiments.

The coverage guarantee and seed-42 totals withstand scrutiny. Other advice is
narrowed: the >= 2 duplicate threshold is a proposed PoC rule clarification, not
proof that a collection was unauthorised; the headers-only provider cannot infer
rate units from values it never receives; and validating one consistent month
is enough without introducing general multi-month support.

The audit also found a weakness in the assistant's own tests. An incorrect
manifest description survived the original eight tests after regenerated
fixtures replaced the snapshots. A new source-based description check closes
that demonstrated gap. All nine tests pass on the unchanged working generator;
three separate description mutations are rejected even after regeneration.

**Revised review outcome:** the required three-answer exchange is complete, and
the reviewer's corrections are recorded. The PRD did not explicitly require the
extra compulsory round; that was the reviewer's interpretation and is withdrawn.
This does not claim the owner endorsed the revised wording. M2 was unstarted
at the time of that audit; the owner subsequently directed the next milestone.

### Independent second-pass handoff

The owner supplied a Grok second-pass report targeting hydroid commit `ba7c5fa`.
Hydroid matched that commit with a clean worktree when implementation resumed.
The report confirmed the numerical/coverage claims and that the ninth test
catches wrong numbers in the known slots after fixture regeneration. It also
demonstrated remaining prose holes: additional later numbers, changed relation
words, changed posting-count prose, extended dates and wrong exception wording.
These remain scoped limitations, not new M1 blockers or new M1 tests.

The owner explicitly declared the M1 gate complete, withdrew any extra quiz,
and directed work on M2. The handoff is attributed to the owner-supplied report;
the builder has not claimed to rerun every second-pass mutation.

## M2: Deterministic reconciliation engine and scoring

**Build status:** implemented; all 37 tests passed at M2 completion (9 M1, 28 M2).
**Commit subject:** `feat: implement deterministic reconciliation and ground-truth scoring`.
**Owner explain-back:** written answers are not recorded. After the M1/M2
CodeRabbit reviews, the owner explicitly directed continuation of the build;
M3 proceeded on that instruction. No owner answers or agreement are invented.
The brief and three M2 discussion prompts remain below as interview preparation.

### What this piece does

It loads the three CSVs using an explicit mapping, then compares cash and margins
using exact integer arithmetic. It detects zero net receipts, the declared
duplicate-direct-debit pattern, and charged margins above contract. Each result
contains unchanged source records and a stable ID. A separate scorer compares
the detected identities with the seeded answer key and preserves every missed
or spurious entry. The engine has no LLM call and does not see the answer key
during detection.

### Three choices and why

1. **Exact arithmetic with a small data contract.** Integer cents and basis
   points avoid rounding decisions. All files must cover one month, and rate
   units are explicit. This tests the brief's rules without introducing a
   multi-month or currency-conversion system.
2. **Visible missing mappings, clear invalid-data errors.** An unmapped amount
   stays missing and skips dependent checks; the score exposes missed errors.
   A mapped value such as `NaN` is rejected. Inventing zero values could create
   false missing-payment claims; guessing a mapping would defeat the exercise.
3. **Evidence and scoring are separate from detection.** Raw CSV records are
   preserved and copied into each exception. Scoring happens only after the
   engine returns. The duplicate rule requires an exact net multiple >= 2 but
   makes no claim about authorisation that the columns cannot establish.

### Verification

At M2 completion, `python3 -m unittest discover tests -v` passed 37 tests on Python 3.13.3.
Seed 42: 12 true positives (four of each type), precision 1.0, recall 1.0,
zero false positives and zero missed entries. Omitting the servicing amount or
payments amount mapping produces a diagnostic, four rate exceptions, recall
1/3 and eight verbatim missed entries. A plausible numeric-column swap also
reduces recall, showing that structurally valid mapping is not semantic proof.

Hand-authored tests include split and partial payments, reversals, zero schedules,
exact cent boundaries, large amounts, direct-debit versus other methods, equal
and one-basis-point margins, overlapping exceptions, aggregate cancellation,
malformed data, duplicate source keys, and period mismatches. Evidence tests
verify raw quoting, multiline records, source line numbers and non-mutation.
The import-graph guard is tested against an indirect OpenAI import and a
provider import through a package initialiser.

The engine checkpoint is not a graph checkpoint: M5 still must ensure no graph
path calls it before human confirmation. General prose validation belongs to
M4. A perfect synthetic identity score does not establish those later controls
or real-world detection performance. See [ENGINE.md](ENGINE.md) for the full
interface and declared boundaries.

### M2 discussion prompts

1. Removing an amount mapping leaves four rate breaches and recall 1/3. Why is
   that more honest than substituting zero or guessing the missing mapping?
2. Why does 500 + 500 against a schedule of 1000 stay clean, while 1500 + 500
   triggers this PoC's duplicate pattern? What still cannot be inferred?
3. What do verbatim evidence and the separate scorer establish, and why do we
   still need the human graph checkpoint and rationale validators later?

### Owner answers

1. Not yet recorded.
2. Not yet recorded.
3. Not yet recorded.

## M3: Mock/OpenAI provider interface

**Build status:** implemented; all 59 tests pass (9 M1, 28 M2, 22 M3).
**Commit subject:** `feat: add mock and OpenAI providers with call records`.
**Owner explain-back:** not yet recorded. The owner authorised this build step;
live OpenAI execution has not been authorised or attempted.

### What this piece does

It supplies three operations behind one interface: propose a column mapping,
classify an existing engine exception and draft its explanation/remediation
note. Mock mode uses deterministic aliases and templates. OpenAI mode sends
documented API requests and captures available outputs and token usage. The
engine remains independent and owns every reconciliation calculation.

### Three choices and why

1. **Explicit modes and honest failure.** Mock is the default; a key alone does
   not activate OpenAI. Failed real calls raise an error and retain audit data.
   Automatically substituting mock output would conceal whether the model ran.
2. **Structured responses with local contract checks.** A fixed model snapshot
   and JSON-schema requests constrain the returned shape. Local checks still
   reject refusals, truncation, malformed JSON, invented types and invalid
   confidence. These are shape checks; fabricated prose remains M4's job.
3. **Record measured data without pretending it is judgment.** Each operation
   captures messages, identity, latency and available usage. Mock has zero model
   tokens and fixed uncalibrated confidence; absent live usage stays unknown.
   No validator score, cost or PASS/BLOCK decision is fabricated by the provider.

### Verification

`python3 -m unittest discover tests -v` passes 59 tests on Python 3.13.3.
The new 22 tests exercise mock/OpenAI output parity and the keyless seam:
3 mappings plus 24 classify/draft operations for all 12 engine exceptions,
zero model tokens, unchanged recall 1.0 and zero false positives.

Scripted OpenAI responses test request formatting, recorded token usage,
malformed output, invalid classifications/mappings, refusals, truncation,
unknown/inconsistent usage and unavailable transport. HTTP tests inspect the
request URL, body, headers and timeout with simulated I/O. Failures do not
retry or switch providers. Raw source evidence reaches the draft prompt without
local path metadata. The engine import-graph guard remains green.

The official API, structured-output and model documentation were checked; links
and detailed limitations are in [PROVIDERS.md](PROVIDERS.md). There has been no
live OpenAI call, no measured model-quality result, no policy verdict and no
graph checkpoint. Full R3 pipeline acceptance waits for M4/M5 integration.

### M3 discussion prompts

1. Why must a successful schema check still allow M4 to block a rationale that
   invents a payment amount or instruction?
2. Why do mock confidence 0.95 and zero mock tokens tell us nothing about live
   model judgment quality, and why does missing live usage stay unknown?
3. When OpenAI refuses or times out after the engine has run, which results
   remain valid, and what would silent fallback hide?

### Owner answers

1. Not yet recorded.
2. Not yet recorded.
3. Not yet recorded.

## M4–M7 · Credential-free pipeline and dashboard

The owner explicitly requested continued building, a custom dashboard and local
Qwen while credentials are unavailable. This supersedes the original no-UI
constraint and pauses between milestones. Later owner comprehension answers
have not been provided; no agreement or answers are invented here.

The completed local workflow ingests/scans three files, proposes mappings,
pauses at a real LangGraph interrupt, computes exceptions after confirmation,
classifies/drafts, validates and separates passed explanations from held drafts.
FastAPI and the dashboard expose safe evidence and analytics. The Disseqt seam
writes typed JSONL and can send the same spans with live credentials later.

Three decisions to defend:

1. Validators produce checks, not truth certificates. Numeric/date/identifier
   membership catches inventions but can miss reversed relationships or swapped
   values. The engine finding and source evidence remain visible beside prose.
2. A model outage or blocked draft never erases deterministic results. Failed
   inference is retained and labelled; public analytics cannot leak held prose.
   Raw output remains only in the local developer audit and private state.
3. Integration status is explicit. Qwen actually ran locally. OpenAI remains
   simulated in tests; Disseqt's current Python SDK wire format is verified with
   a fake server. Credentials alone still need a live acceptance check before
   claiming registry/policy binding or dashboard visibility.

Verification: 86 offline tests pass, including numerical boundaries, each guard
seen to fail, poisoned-provider end-to-end, repeated confirmation, wrong mapping,
provider failure and captured-HTTP trace parity. Browser checks exercised desktop
and mobile mapping, results, source evidence, search, activity and connections.

The exact owner-selected Qwen model ran against seed 42 / 40 loans on Ollama
0.34.0: 12 engine findings, recall 1.0, zero false positives; 10 explanations
passed and two were held. One hold was unsupported evidence-row numbering, the
other token-limit truncation. There were 27 attempted model calls and 9,775
recorded tokens in 189.46 seconds. See [LOCAL_QWEN_RUN](LOCAL_QWEN_RUN.md).
The test harness's mapping confirmation is not owner approval.

No new quiz blocks this build. The owner can use these briefs for later interview
preparation without reopening M1 or changing the original A1–A3 answers.
