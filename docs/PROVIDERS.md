# M3: LLM provider contract

`app/providers.py` implements the PRD's three-operation interface. The default
is deterministic mock mode. The engine never imports the provider module; the
existing import-graph test still enforces that boundary.

## Interface and behaviour

| Operation | Public output | Limits |
| --- | --- | --- |
| `propose_mapping(headers, canonical)` | `{raw_header: canonical_field}` | Unknown/ambiguous names remain unresolved. The caller receives a proposal, not an approval. No values or unit metadata are supplied. |
| `classify(detail, engine_type)` | `{type: str, confidence: float}` | Type must be in the closed set and confidence finite in [0, 1]. An in-set disagreement is preserved; the engine type is never rewritten. |
| `draft_rationale(exception)` | `str` | The draft is returned unchanged after checking its shape. Schema validity is not faithfulness or permission to show it to an analyst. |

Mapping responses use a JSON wrapper with a slot for every supplied header;
unresolved slots are null. The provider's public result omits null slots.
Invented headers, invented canonical names, duplicate canonical assignments and
malformed shapes raise `ProviderError`. No output is silently repaired.

`MockProvider` normalises case, spaces, underscores and hyphens, then checks an
explicit alias table. If two headers compete for one canonical field, neither
is guessed. Classification repeats the engine type with fixed confidence 0.95;
that number is a fixture value, not measured quality. Its rationale quotes the
engine detail verbatim and appends a generic instruction for human review.
It emits no validator score, verdict or claim that a real model was called.

`OpenAIProvider` uses a small standard-library HTTPS transport, so keyless setup
does not need a model SDK. The transport issues one request with a bounded
timeout, rejects redirects, and does not automatically retry or fall back.
Tests can substitute a scripted transport without contacting OpenAI.

## OpenAI protocol and sources

The chosen default snapshot is `gpt-4.1-mini-2025-04-14`. The official model page
lists that snapshot and support for Chat Completions and structured outputs.
This is a bounded implementation choice for the PRD, not a comparative claim
that this model is best at mapping. [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini)

Requests use `/v1/chat/completions`, temperature 0, a 1024 completion-token limit,
`store: false` and strict JSON-schema `response_format`. The API reference
documents these request controls and response usage fields. Zero temperature
and a snapshot do not establish byte-identical model output. [Create chat completion](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create)

The PRD asks for JSON response formatting. We use `json_schema` rather than
the older `json_object` mode because the official guide distinguishes schema
adherence from merely parseable JSON. Local checks still reject wrong shapes,
duplicate JSON keys, nonfinite confidence, refusal, truncation and nonstandard
completion termination. This does not validate the factual meaning of prose.
[Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

These sources were checked on 2026-09-11. No customer account access, successful
live call, live validator score or real-run cost is claimed by M3.

## Configuration

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `LLM_PROVIDER` | `mock` | Explicit `mock` or `openai` selection. A key alone does not activate OpenAI. |
| `OPENAI_API_KEY` | none | Required only for OpenAI mode; read by `get_provider()` from the process environment. |
| `OPENAI_MODEL` | `gpt-4.1-mini-2025-04-14` | Optional override; it must support the configured request parameters. Incompatible-model errors are surfaced. |

The code reads process environment variables; it does not automatically load
`.env` files. Missing keys, empty model names and unknown provider names are
configuration errors. Do not put credentials in committed files. The P1 live
OpenAI run remains subject to the owner's approval under the PRD; local work
and the entire test suite need no credentials.

For a zero-credential example from the repository root:

```bash
python3 - <<'PY'
import json
from app.providers import get_provider

provider = get_provider({})
print(provider.propose_mapping(["LoanIdentifier", "UnknownColumn"], ["loan_id"]))
print(provider.classify(
    "Loan SYN-L000005: scheduled 2580.61; net received 0.00.", "MISSING_PAYMENT",
))
print(json.dumps({
    "provider": provider.provider_name,
    "operations": len(provider.calls),
    "model_tokens": sum(call["usage"]["total_tokens"] for call in provider.calls),
}))
PY
```

## Call records and errors

Each provider instance belongs to one run. Its `calls` list stores an ID,
operation, provider/model identity, mock flag, UTC start time, measured latency,
input/output messages, response ID, returned model, finish reason, usage, status,
available raw response and error information. Raw response fields are retained
even when subsequent output-contract checks fail. Transport failures have no
invented response or usage.

OpenAI token counts are taken from the response; missing usage remains null,
not zero. Malformed or inconsistent usage is rejected while the raw response
remains available. Mock counts are explicitly zero. No tokenisation estimate,
cost estimate, validator score or PASS/BLOCK verdict is invented here.

Draft requests contain raw evidence rows, engine detail, type and loan ID.
Absolute local source paths and bookkeeping line numbers are not model inputs.
API keys are transport headers, not stored prompt or call-record fields.

`ProviderError` communicates an unusable model step. The future graph must keep
already-computed engine results and route affected output to human review.
It must not replace an OpenAI failure with a successful-looking mock response.
There is no held-output queue or policy enforcement in M3 itself.

## Validation and remaining milestone work

All 59 tests pass: 9 M1, 28 M2 and 22 M3. Tests cover public shape parity,
explicit selection, aliases/ambiguity, a keyless mapping/engine/drafting smoke
test, request controls, usage, raw response retention, HTTP handling and failure
paths. OpenAI responses and HTTP I/O are simulated; no test calls the live API.

The keyless smoke test executes 3 mapping operations and 24 classify/draft
operations for the 12 engine exceptions. It reports zero model tokens while
preserving the engine's recall 1.0 and zero false positives. It does not compute
validator scores or demonstrate human confirmation. The PRD's full-pipeline
acceptance depends on the later M4 validators and M5 graph.

A test deliberately returns plausible but fabricated payment prose in a valid
response shape; M3 preserves that draft for the later validator to inspect.
Another preserves an in-set classification disagreement. M4/M5 must address
those conditions before analyst release. Input injection/PII scanning likewise
belongs before real provider calls in that future graph. Prompts alone are not
proof of those controls, and no new general prose validator is added at M1/M3.
