"""Official SDK transport adapter; the graph and local audit stay unchanged.

The SDK's synchronous send_spans return value is checked. Its buffered client's
flush() returns None and cannot establish delivery success. High-level client
and helper compatibility is exercised separately in the SDK tests.
"""

import json
from urllib.parse import urlsplit

from disseqt_agentic_sdk.models.span import EnrichedSpan
from disseqt_agentic_sdk.transport import HTTPTransport


class SDKTransport:
    def __init__(self, api_key, project_id, endpoint, timeout=10):
        if not isinstance(api_key, str) or not api_key.strip() or not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("SDK transport requires an API key and project ID; use the local SDK smoke harness without credentials")
        parsed = urlsplit(endpoint)
        local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("SDK endpoint must use HTTPS (HTTP allowed for loopback tests)")
        if not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("Invalid SDK endpoint")
        self.mode = "sdk-local" if local else "sdk-live"
        self.project_id = project_id
        self.transport = HTTPTransport(endpoint=endpoint, api_key=api_key, timeout=timeout, max_retries=0)
        self.transport.session.max_redirects = 0
        if local:
            self.transport.session.trust_env = False

    def send(self, payload):
        resource = payload["resource"]["attributes"]
        spans = []
        for trace in payload["traces"]:
            for span in trace["spans"]:
                spans.append(EnrichedSpan(
                    trace_id=trace["traceId"], span_id=span["spanId"], parent_span_id=span["parentSpanId"],
                    name=span["name"], kind=span["spanKind"], root=not span["parentSpanId"],
                    start_time_unix_nano=span["startTimeMs"] * 1_000_000,
                    end_time_unix_nano=span["endTimeMs"] * 1_000_000,
                    duration_ns=(span["endTimeMs"] - span["startTimeMs"]) * 1_000_000,
                    status_code=span["status"], project_id=self.project_id,
                    service_name=resource["service.name"], service_version=resource["service.version"],
                    environment=resource["deployment.environment"],
                    attributes_json=json.dumps({**span.get("attributes", {}), **{
                        key: value for key, value in resource.items() if key.startswith("uc1.")
                    }}, allow_nan=False),
                ))
        if not self.transport.send_spans(spans):
            raise RuntimeError("Disseqt SDK delivery failed; local audit retained")

    def close(self):
        self.transport.session.close()
