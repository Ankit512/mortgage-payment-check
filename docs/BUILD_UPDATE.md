# Local dashboard and integration update — 11 September 2026

The owner explicitly requested continued development without Disseqt/OpenAI
keys, a custom dashboard, configurable integrations, and local Qwen inference.
This supersedes the original PRD's no-dashboard constraint and pauses between
milestones. The original PRD and owner A1–A3 answers remain unchanged. Written
answers to later discussion prompts have not been supplied or inferred.

The owner subsequently selected the exact model:
`hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M`.
This is a community distillation distributed by Empero, not an untrained model
or an official Qwen 4B release. No training/fine-tuning was performed in this
project. The source is the [publisher's model card](https://huggingface.co/empero-ai/Qwen3.8-4B-Distill-GGUF).

## Delivered behavior

- Six local validators, strict PASS/BLOCK thresholds, and additional checks for
  provider success, agreement with the engine and mapping completeness.
- A LangGraph interrupt with an in-memory checkpointer. Start returns a paused
  run; confirmation resumes it. Repeated confirmation is rejected.
- FastAPI endpoints, a responsive dashboard, synthetic CSV uploads, editable
  mapping/sample values, source evidence, separate passed/held queues, exports,
  run activity, token/latency statistics and a user-supplied baseline.
- Local Ollama, mock and OpenAI behind the same provider interface. Failed
  inference is recorded honestly; deterministic evidence survives. An
  unavailable provider stops subsequent prose calls in that run.
- Local JSONL and configurable Disseqt transport based on its current published
  Python SDK's wire shape. No keys were used and no live integration is claimed.

## Runtime finding

The requested GGUF downloaded successfully. Installed Ollama **0.21.2** failed
before inference: `qwen3next: layer 32 missing attn_qkv/attn_gate projections`.
An isolated official **0.34.0** runtime on `127.0.0.1:11435` loaded the same
model and completed a real mapping request. The existing Ollama app/service
was not replaced. Standalone runtime files are ignored under
`tmp/ollama-runtime/`; model weights live in the existing Ollama cache.

Use an Ollama release compatible with this GGUF. On this machine, set
`OLLAMA_BASE_URL=http://127.0.0.1:11435` while the isolated runtime is serving.
The normal default remains port 11434 so a standard compatible installation
needs no code change. A tag is not an immutable model identity; the actual
download digest is recorded in the local-run report.

## Validation limits retained

Faithfulness checks numeric, date and synthetic identifier membership using
Decimal, avoiding float rounding while accepting equivalent numeric formats.
This is a deliberate strengthening of the PRD's float-comparison wording.
It detects later appended ungrounded numbers and foreign periods, but does not
prove relationships, field assignments, intent or semantic truth. Grounded
values can still be swapped between fields. Number words and arbitrary
identifier formats are not comprehensively parsed. Known bad examples and
intentional limits are in `tests/test_validators.py`.

Injection/PII scans use patterns, not a complete security or PII detector.
Input values and headers are scanned before any model call. Blocked drafts
are retained in developer JSONL and private run state; public run/analytics
responses omit them. The held queue shows trusted engine facts and validation
findings only. There is no automatic release or payment execution endpoint.

The UI's approval checkbox is an interaction guard, not identity verification.
The server trusts an explicit API confirmation; this single-user local PoC
does not authenticate reviewers. It binds to loopback in documented commands.

Baseline input is available but no manual baseline has been invented.
OpenAI cost remains unknown until model pricing is configured; local API spend
is zero, excluding electricity/hardware. Mock scores describe validator checks
against templates, not model quality.

## Subsequent SDK test request

The owner then asked for tests using the actual SDK and Qwen instead of OpenAI.
The SDK is now a pinned runtime dependency with an explicit transport selector.
`make sdk-demo` uses real local Qwen and fixed dummy Disseqt identifiers against
a loopback capture server. No cloud validator outcome is claimed. See
[DISSEQT_INTEGRATION](DISSEQT_INTEGRATION.md) for the current implementation.
