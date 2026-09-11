# Disseqt integration contract

Current implementation speaks the custom JSON trace format found in the
published [disseqt-ai-sdk 0.8.0](https://pypi.org/project/disseqt-ai-sdk/0.8.0/)
Python wheel. The original PRD's Node-only premise is outdated. The wheel was
downloaded for inspection, not installed as a runtime dependency.

Inspected source: `disseqt_agentic_sdk/transport/http.py`, `models/span.py`,
`enums/span_kind.py`, `client/client.py`, plus `disseqt_sdk/client.py` for
validator authentication. No backend account or dashboard was accessed.

## Trace format

The endpoint defaults to:
`https://api.disseqt.ai/agentic-monitoring/api/v1/traces`.

```json
{
  "resource": {
    "attributes": {
      "service.name": "mortgage-capital-uc1",
      "service.version": "0.1.0",
      "deployment.environment": "local-poc",
      "project.id": "local"
    }
  },
  "traces": [{
    "traceId": "run UUID",
    "spans": [{
      "traceId": "run UUID",
      "spanId": "span UUID",
      "parentSpanId": "root span UUID",
      "name": "reconcile_engine",
      "spanKind": "TOOL_EXEC",
      "startTimeMs": 0,
      "endTimeMs": 1,
      "status": "OK",
      "attributes": {}
    }]
  }]
}
```

Kinds are `AGENT_EXEC`, `MODEL_EXEC`, `TOOL_EXEC`; statuses are `OK`/`ERROR`.
Model attributes include provider/model identity, usage and `uc1.call` containing
unaltered input/output call records. Run activity APIs remove these raw records
and return safe summaries, preventing held prose from leaking through analytics.
Tool-span attributes also retain engine evidence, fixture scores and each local
validation score/finding/verdict under `uc1.*` names. These custom attributes are
local-policy evidence, not a claim of remote Disseqt validation.

LocalTransport writes each envelope as one JSONL line. LiveTransport receives the
same envelope, copies it, and adds `api.key`, `project.id`, `ingestion_url` to
resource attributes, matching SDK 0.8.0's agentic transport. It also sends
`X-API-Key` and `X-Project-Id` headers. Secrets are attached **only** at the network
boundary and never persisted. Therefore span sequences match exactly between
local and live transports, while authentication metadata intentionally differs.
The PRD's literal identical-entire-payload requirement is narrowed to identical
trace data to avoid writing credentials to disk.

`DISSEQT_SERVICE_NAME` controls service attribution. Optional
`DISSEQT_APPLICATION_ID` is retained as `uc1.application_id`, an explicitly custom
attribute; it is not evidence of accepted registry binding or a documented
native application-ID field. The final root span closes after the run; paused
runs retain completed steps while the overall root remains open.

## Verification and remaining work

`tests/test_disseqt_wire.py` starts a loopback HTTP server, captures requests,
checks headers, resource authentication, span sequence parity and local secret
exclusion. A failed remote send retains JSONL and exposes a safe delivery error.
No retries, queues or silent success are invented.

All six validators and PASS/BLOCK decisions currently execute locally. No
remote validator, application registration, policy publication/binding, or
Disseqt dashboard assertion is made. The assignment asks for these live
capabilities; the original PRD defers several. They remain a credential-dependent
verification/integration step. Add credentials and enable live transport for the
first trace smoke test, then confirm application association and dashboard
visibility with Disseqt before claiming those requirements complete.
