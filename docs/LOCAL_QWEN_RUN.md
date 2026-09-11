# Actual local Qwen run — 11 September 2026

This is measured local inference, not mock output and not a live OpenAI run.
Machine: Apple M4, 16 GB RAM, macOS arm64, Python 3.13.3. Model:
`hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M`.

The [publisher describes a community distillation](https://huggingface.co/empero-ai/Qwen3.8-4B-Distill-GGUF),
not an official Qwen release of this size. We use the supplied artifact without
training or changing its weights. No benchmark claims from its card are adopted.

Ollama model digest:
`56c1b4004458f7dfa3d1e5d76d74200ea42d8d6cc6ba9e7010d08b8461061e55`.
Downloaded size: 2,783,446,711 bytes. Ollama reports architecture `qwen35`, 4.33B
parameters and quantization `unknown`; the requested artifact tag is Q4_K_M.
Those metadata facts are retained separately rather than inventing an inferred
quantization measurement.

Installed Ollama 0.21.2 failed to load the artifact. An isolated official
[Ollama 0.34.0 release](https://github.com/ollama/ollama/releases/tag/v0.34.0)
loaded it on port 11435 and handled all requests. The standard local Ollama
service was not replaced. The provider uses `/api/chat`, JSON-schema `format`,
`stream=false`, `think=false`, temperature 0, context 8192 and output cap 1024.
These are reproducible settings, not a byte-identical inference guarantee.
[Ollama's chat API](https://docs.ollama.com/api/chat) documents the schema and
native evaluation-count response fields.

## Result

Run `f127b502-7ee7-4b26-9036-cf3f142cc5b8`, seed 42 / 40 loans:

| Measurement | Actual result |
| --- | --- |
| Correct proposals | All three file mappings |
| Engine findings | 12: four of each supported exception type |
| Fixture precision / recall | 1.0 / 1.0 |
| False positives / false negatives | 0 / 0 |
| Model operations | 27 attempted: 3 mapping, 12 classification, 12 drafting |
| Passed explanations | 10 |
| Held explanations | 2 |
| Recorded tokens | 9,775 |
| Active processing | 189,461 ms (about 3 minutes 9 seconds) |
| External model API spend | $0; local compute costs excluded |
| Live Disseqt requests | None; local JSONL only |

The harness submitted the API mapping confirmation as an automated integration
test. This is **not** a recorded human review or an owner comprehension answer.
All original engine findings survived, including those with failed model steps.

## The two holds are different

- **SYN-L000013, margin breach:** Qwen cited evidence “row 1” and “row 3”.
  We send an array of raw rows without numeric citation labels. The validator
  therefore found numeric references 1 and 3 ungrounded. This is a conservative
  citation-format false positive, not proof the monetary values were invented.
  It is a practical limitation to report; the check was not weakened to improve
  this run's pass rate.
- **SYN-L000015, duplicate debit:** the draft repeated the same sentence until
  it reached the 1024-token cap. Ollama returned `done_reason=length` and the
  provider rejected it as incomplete. No truncated draft reached the analyst.
  This is a generation failure, not a fabricated-amount finding.

Mean faithfulness: 0.8333; answer relevance: 0.9167; provider success: 0.9167.
Classification agreement, closed-set classification, mapping completeness,
execution order and input-scan means: 1.0. These scores are computed local
checks; they do not prove every passed explanation is semantically correct.

The machine-readable [run record](local_qwen_run.json) contains safe call/span
summaries, scores and hold reasons. Raw model output remains in the ignored
local trace generated during this run (`tmp/traces/<run_id>.jsonl` for this
pre-final configuration); the final server defaults to `traces/<run_id>.jsonl`.
No thresholds or prompts were changed after observing these outcomes.

## Final server verification

After completing trace-score/evidence emission, the final server ran the same
40-loan dataset again as `7a6b44b7-c1ef-4a78-b5d8-ed76f9577ab2`.
It again found 12 exceptions, with 10 passed / 2 held explanations and 9,775
recorded tokens. Warm-run active processing was 161,721 ms. The local trace
contains all 12 computed policy decisions and source evidence at
`traces/7a6b44b7-c1ef-4a78-b5d8-ed76f9577ab2.jsonl`.

Browser checks on this final Qwen run confirmed the two held findings, source
access and absence of blocked prose, including at mobile width. The
[dashboard capture](dashboard.png) and [held-queue capture](dashboard-held.png)
show the actual final run. Both confirmations were automated integration tests.
