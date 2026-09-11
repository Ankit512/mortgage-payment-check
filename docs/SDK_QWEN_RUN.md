# Official Disseqt SDK + real local Qwen verification

Run date: 11 September 2026. Run ID:
`309f5b84-7a35-4486-93ab-8716a09354fd`.

This run used installed `disseqt-ai-sdk==0.8.0`, its native `EnrichedSpan` models
and `HTTPTransport.send_spans()`, the actual FastAPI/LangGraph workflow, and
`hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M` on local Ollama 0.34.0.
The numerical engine and six guards remained deterministic local code.

The Disseqt receiver was an ephemeral loopback capture server, using fixed
public dummy identifiers. SDK serialization and HTTP were real. Disseqt cloud
authentication, hosted validation and dashboard ingestion were not exercised.
The harness explicitly forbids OpenAI provider calls and constructs its own
environment without inheriting credentials.

| Check | Observed result |
| --- | --- |
| Dataset | Seed 42, 40 synthetic loans |
| Engine findings | 12; recall 1.0; zero false positives/negatives |
| Explanations | 10 passed, 2 held |
| Real Qwen operations | 27 |
| Actual Qwen tokens | 9,775 |
| Tokens captured through SDK-native usage fields | 9,775 |
| SDK HTTP requests / spans | 50 / 50 |
| Computed policy verdicts captured | 12 |
| SDK spans equal local audit spans | Yes, including IDs, timestamps, evidence and scores |
| Delivery errors | 0 |
| Active processing time | 217,225 ms (about 3 minutes 37 seconds) |
| OpenAI calls / Disseqt cloud requests | 0 / 0 |
| Real credentials used | None |

The two holds match the earlier local-Qwen observations: unsupported evidence
row numbering for SYN-L000013 and a repetitive draft reaching the token cap for
SYN-L000015. They are not both monetary hallucinations. No threshold or model
prompt was changed to force this SDK run to pass.

The graph paused before reconciliation and was resumed by an automated test
confirmation. This does not claim owner review. The full request captures and
JSONL remain under the ignored `tmp/sdk-qwen-verification/` directory. The
committed [machine-readable report](sdk_qwen_run.json) contains safe summary
measurements and hold findings.

## Reproduce

```bash
make install
OLLAMA_BASE_URL=http://127.0.0.1:11435 make sdk-demo
```

Use port 11434 for a compatible standard Ollama installation. The SDK capture
server starts and stops automatically, and no Disseqt/OpenAI keys are read.
The existing dashboard server is unaffected.

The 93-test offline suite includes seven SDK tests: native high-level client
and helpers; adapter/span parity; HTTP failure/redirect handling; unknown usage;
full API/graph integration; the validation-client request/response contract; and
configuration requirements. The validation-client test receives a clearly
canned server score. It proves client plumbing, not hosted faithfulness quality.
See [DISSEQT_INTEGRATION](DISSEQT_INTEGRATION.md) for credential-dependent limits.
