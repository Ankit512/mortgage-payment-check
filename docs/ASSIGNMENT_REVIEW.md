# Assignment review: use case 1

Reviewed the supplied three-page assignment, especially page 2, against
`DISSEQT_UC1_PRD.md`. The PDF is titled *Mortgage Capital: Data Reconciliation &
Anomaly Detection & Risk, Policy & Regulatory Compliance*, prepared by Disseqt AI,
August 2026. Its footer marks it Commercial in Confidence; the PDF has not been
copied into this repository. `docs/PRD.md` preserves the supplied PRD unchanged.

The build implements UC1 only. UC2 is limited to the PRD's planned walkthrough
appendix; no UC2 governance system is being built.

## Requirements and differences to keep visible

| Assignment UC1 step | PRD coverage | Delivery implication |
| --- | --- | --- |
| 1. Ingest repeatable anonymised files with known errors | R1 generator, R2 loader, R5 ingestion | M1 supplies three synthetic files and a seeded answer key. Ingestion comes later. |
| 2. Register in Disseqt's Applications Registry | P2 reserves a registration method | Deferred by the PRD. A reserved method or placeholder application ID is not proof of registration. Actual live registration remains a submission gap until evidenced. |
| 3. LangGraph + FastAPI; mapping, confirmation, deterministic reconciliation, constrained classification, rationale/remediation log | R2-R5 | Preserve the structural human checkpoint. Include an actionable remediation note as requested by the assignment. Only code owns arithmetic. |
| 4. Instrument with DisseqtAgenticClient / SDK | R6 uses a Python wire client because the PRD says the SDK is Node-only | This is a deliberate integration deviation. Verify current official protocol, endpoint and SDK support at M6; do not invent them or treat the PRD's SDK claim as verified. |
| 5. Disseqt validators: faithfulness, context-relevance, answer-relevance, tool-call-accuracy, plan-coherence, injection and PII | R4 implements six local validators, including a closed-classification-set check | Context-relevance and tool-call-accuracy are not separate R4 validators. Local checks are not live Disseqt validator evidence. Revisit coverage at M4/M6 and document anything unimplemented. |
| 6. Publish/bind a realtime policy, return PASS/BLOCK | R4 local thresholds; dashboard policy binding is P2 | A local policy demonstrates holding semantics, but does not prove a policy was published or bound in Disseqt. |
| 7. Record a Week-1 manual-process baseline | R5 baseline API | Implement baseline input, but do not fabricate manual measurements. No real baseline is available in the supplied files. |
| 8. Show timeline, scores, verdicts, cost, latency and drift in Disseqt dashboard | R5 analytics JSON; R6 live/local transport | JSONL and JSON endpoints are local evidence. Live dashboard visibility needs an actual registered application and successful ingest. |

These differences do not block building the PRD's local PoC. They must remain
explicit in the final walkthrough so a passing mock run is never presented as
completion of the assignment's live integration requirements. No live account
access, protocol compatibility or dashboard outcome has been verified at M1.

## Milestone sequence

The user requested the PRD's process: build -> tests green -> commit -> brief ->
owner answers three questions -> next milestone. A code milestone can be built
while its comprehension gate remains pending. Do not invent owner answers.

| Milestone | Scope | State |
| --- | --- | --- |
| M1 | R1: sample generator and answer key | Implemented; validation and commit recorded in EXPLAIN_BACK; owner gate pending |
| M2 | R2: deterministic reconciliation engine and scoring | Not started; waits for M1 answers |
| M3 | R3: mock/OpenAI provider seam | Not started |
| M4 | R4: validators and PASS/BLOCK policy | Not started |
| M5 | R5: LangGraph checkpoint, FastAPI, analytics, baseline | Not started |
| M6 | R6: documented Disseqt wire client and transport parity | Not started |
| M7 | R8: complete README and CTO walkthrough; P1 if time permits | Not started |

Every milestone extends the suite run by `python3 -m unittest discover tests -v`.
M1 fixture audits do not claim R2 engine recall: the engine does not exist yet.
P1 real OpenAI calls require the owner's confirmation as stated in PRD section 7.
Repository visibility and publication remain unresolved; this work is local.
