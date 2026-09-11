# Disseqt integration contract

The project now installs and exercises the official
[disseqt-ai-sdk 0.8.0](https://pypi.org/project/disseqt-ai-sdk/0.8.0/).
Its native transport is available alongside the original direct HTTP adapter.
The original PRD's Node-only premise is outdated. This update follows the owner's
request to test the actual SDK without credentials, using Qwen for inference.

## Reproduce without either API key

```bash
make install
make sdk-demo
```

On this machine, the compatible isolated Ollama runtime serves port 11435:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11435 make sdk-demo
```

The harness starts an ephemeral loopback capture server, supplies fixed dummy
Disseqt identifiers, and runs the real FastAPI/LangGraph pipeline with the exact
owner-selected Qwen model. It does not inherit real credentials. Model calls go
to local Ollama; SDK calls go to the local capture sink. The normal dashboard
server is unaffected. Artifacts are written under `tmp/sdk-smoke-<uuid>/`.

The harness checks the real interrupt, seed-42 recall, actual Qwen token counts,
SDK/local span equality, all computed policy verdicts, delivery success and zero
OpenAI calls. The confirmation is an automated integration test, not owner
review. Hosted Disseqt validators are not invoked by this harness.

## Adapter and SDK behavior

`app/disseqt_sdk.py` converts our completed span envelopes into official SDK
`EnrichedSpan` objects and calls its real `HTTPTransport.send_spans()` method.
The graph, numerical engine and local audit are shared across transports.
The SDK's serialization and HTTP implementation execute without replacing them
with mocks. Only the receiving server is a test sink.

We use the SDK's synchronous boolean delivery result because its high-level
buffered `flush()` returns `None` and discards the transport result. A false
return is surfaced as a delivery error while retaining JSONL. Retries are
configured off, and redirects are rejected. Loopback SDK sessions bypass proxy
environment settings. Session cleanup runs when the FastAPI application exits.

Separate tests exercise the actual `DisseqtAgenticClient`, `start_trace`,
`trace_llm_call` and `trace_tool_call` helpers. Another test calls the official
validation `Client.validate(FaithfulnessValidator(...))` against an explicitly
canned local response. This verifies request routing, headers, serialization
and response parsing; that canned score is not a Disseqt validation result.

## Trace format and Qwen tokens

The default cloud endpoint remains
`https://api.disseqt.ai/agentic-monitoring/api/v1/traces`.
The SDK sends `{resource: {attributes: ...}, traces: [{traceId, spans}]}`.
Each span carries its IDs, name, kind, millisecond start/end times, status and
nonempty attributes. Kinds are `AGENT_EXEC`, `MODEL_EXEC`, `TOOL_EXEC`; statuses
are `OK`/`ERROR`. Empty attributes are omitted to match the SDK serializer.

Model metadata now uses the **SDK's native `agentic.*` conventions**, replacing
the earlier `gen_ai.*` fields. This was a concrete compatibility correction
found while testing the SDK:

| Attribute | Source |
| --- | --- |
| `agentic.provider.name` | `ollama` for actual local Qwen calls |
| `agentic.request.model` | Exact requested model ID |
| `agentic.usage.input_tokens` | Ollama `prompt_eval_count` |
| `agentic.usage.output_tokens` | Ollama `eval_count` |
| `agentic.usage.total_tokens` | Sum of the two measured counts |
| `agentic.input.messages` / `agentic.output.messages` | Actual call messages |
| `uc1.call` | Full call record, including native Ollama response |

Canonical provider fields named `prompt_tokens` and `completion_tokens` are
shared across implementations. They do not imply that OpenAI generated those
tokens. Missing usage stays unknown. No OpenAI API key is needed for Qwen.

Tool-span `uc1.*` attributes retain engine evidence, fixture scores and each
local validation score/finding/verdict. These are local-policy evidence, not
hosted Disseqt evaluation. Public run/analytics responses exclude all raw model
messages so held prose does not leak through the monitoring view.

## Selecting a transport later

| Mode | Behavior |
| --- | --- |
| `DISSEQT_TRANSPORT=local` | JSONL only, no credentials; default |
| `DISSEQT_TRANSPORT=sdk` | Official SDK transport plus JSONL |
| `DISSEQT_TRANSPORT=live` | Original direct HTTP adapter plus JSONL |

For a real Disseqt account, set `DISSEQT_API_KEY`, `DISSEQT_PROJECT_ID`, optional
`DISSEQT_ENDPOINT`, and select `sdk`. A key alone never activates transmission.
The SDK places authentication in `resource.attributes["api.key"]` and
`project.id`. The direct HTTP adapter also sends `X-API-Key`/`X-Project-Id`
headers. Authentication is added only at transmission; local JSONL contains no
key. Therefore parity means identical trace data, not identical secret-bearing
HTTP envelopes.

`DISSEQT_SERVICE_NAME` controls SDK-native service attribution. Optional
`DISSEQT_APPLICATION_ID` remains an explicitly custom `uc1.application_id`
attribute. The SDK adapter carries it at span level because the SDK controls
resource serialization. This is not proof of registry binding.

## What credentials are still required for

We have not verified account authentication, application registration, hosted
validators, policy publication/binding, billing or cloud dashboard visibility.
A local capture server cannot prove those things.

The SDK's [hosted LLM-as-a-judge feature](https://github.com/DisseqtAI/disseqt-python-sdk/blob/main/docs/llm-as-a-judge.md)
also requires a saved Disseqt LLM integration ID and account access. Selecting a
local Qwen model in this application does not create that integration or make
this machine's loopback endpoint reachable by Disseqt's servers. Our six guards
continue to run locally; no hosted judge score is fabricated.
