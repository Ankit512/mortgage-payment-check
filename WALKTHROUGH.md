# UC1 reviewer walkthrough

This build demonstrates a mortgage reconciliation workflow with human-approved
mapping, deterministic detection, guarded model explanations and a complete
local audit. It runs in mock or real local-Qwen mode without paid API keys.
Live OpenAI/Disseqt outcomes are not claimed.

## Six-minute demo

1. **0:00–0:45 · State the boundary.** Open the dashboard and start seed 42 / 40
   loans. Choose explicit mock for an instant mechanics demo or Qwen for actual
   local inference. Servicing, payments and investor files intentionally have
   different raw headers. Their equal row counts hide per-loan discrepancies.
2. **0:45–1:30 · Show the checkpoint.** Inspect proposed mapping and sample values.
   No engine findings exist yet. The graph has a saved LangGraph interrupt.
   Correct a mapping if needed, check the review box, and confirm. API approval
   is explicit; reviewer identity is not authenticated in this local PoC.
3. **1:30–2:15 · Follow the evidence.** The engine finds four missing payments,
   four duplicate debit patterns and four margin breaches. Open SYN-L000005:
   scheduled 2580.61, zero postings. Open SYN-L000011: two postings of 1259.90.
   Open SYN-L000013: 2.59% charged versus 2.00% contract. All arithmetic is code.
4. **2:15–3:15 · Show why PASS is limited.** Evidence dialogs show engine facts,
   validated model text and verbatim CSV rows. The six guards produce measured
   scores. Unknown numbers/IDs can fail; correct numbers in wrong relationships
   can survive. PASS means the configured checks passed, not semantic certainty.
5. **3:15–4:15 · Demonstrate a failure.** Run the poisoned-provider test below:
   all 12 findings remain, all 12 drafts are held, and analyst responses contain
   no poisoned prose. A separate unavailable-provider test preserves engine
   results and labels unattempted prose honestly. No model fallback conceals it.
6. **4:15–5:15 · Inspect activity and connection seams.** Run activity shows model,
   tool and agent spans, actual token usage and processing time. Local API spend
   excludes compute costs. Connections shows Qwen, OpenAI and Disseqt settings;
   adding credentials later changes the server environment, not the engine/UI.
7. **5:15–6:00 · Defend the limits.** Recall 1.0/zero false positives demonstrates
   seeded-fixture agreement. The answer key comes from the generator, not a real
   operational ground-truth set. Investor cash is derived, authorisation data
   is absent, and a baseline must be observed before drift can be interpreted.

## Demonstrate the guards

```bash
.venv/bin/python -m unittest discover tests -p 'test_validators.py' -v
.venv/bin/python -m unittest discover tests -p 'test_pipeline.py' -v
```

The tests cover appended invented amounts, foreign/full-width identifiers,
changed dates, off-topic explanations, payment instructions, invalid types,
draft-before-engine order, input instruction overrides and embedded PII.
Pipeline tests prove the interrupt, model failure, disagreement, poisoned-output
holding, no public prose leakage, repeat-confirm rejection and wrong-mapping
recall of 1/3. Hand-authored engine boundaries are independent of the generator.

An API harness submitting a confirmation is an automated integration test,
not an invented record of owner approval. Owner A1–A3 remain verbatim in the
[explain-back trail](docs/EXPLAIN_BACK.md).

## Defensible design choices

**Propose → approve → compute.** Header mapping uses the model, approval is an
explicit checkpoint, and the engine performs every numerical comparison. The
mock provider is a limited alias table/template fixture. Models never receive
permission to calculate, execute transfers or release their own explanations.

**Retain what can be trusted.** A failed provider does not invalidate completed
engine findings. Held drafts remain in local developer audit files, while the
analyst sees engine facts, source evidence and reasons for the hold. No release
endpoint or payment action exists in this build.

**Small modules with explicit boundaries.** Providers share a strict output
contract and call records. The graph handles orchestration; validators own local
scores; the wire client owns trace delivery. An engine import-graph test prevents
a provider dependency entering numerical computation.

**Honest integration evidence.** Current Disseqt Python SDK source was inspected;
the custom wire format and auth handling were tested against a fake HTTP server.
Actual remote registry, validator/policy binding, ingestion and dashboard
visibility require credentials and a subsequent live smoke test. See
[DISSEQT_INTEGRATION](docs/DISSEQT_INTEGRATION.md).

## UC2 mapping appendix — evidence reuse only

This is a mapping to the assignment's requested control themes, not a legal
compliance opinion or a separate UC2 implementation.

| Assignment UC2 theme | Evidence available from UC1 | Remaining limit |
| --- | --- | --- |
| Article 15: accuracy/robustness | Ground-truth scores, numerical boundary tests, failed validators, provider-error traces | Synthetic performance and pattern checks do not prove production accuracy/security |
| Article 14: human oversight | Persisted-in-session mapping interrupt, explicit confirmation span, held-output queue | No authenticated reviewer identity, formal oversight procedure or durable approval record |
| Article 12: logging | Typed tool/model/agent spans, usage, source evidence, local JSONL | No tamper-evident retention or live Disseqt audit verification |

No production data, UC2 application, external application registration or
submission email is created by this walkthrough.
