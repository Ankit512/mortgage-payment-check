"""Local audit + optional Disseqt transport, based on Python SDK 0.8.0 wire shape.

Credentials are attached only at the live network boundary, never persisted in
JSONL. Both transports receive identical trace/span data. No remote registration
or policy enforcement is claimed by successful trace delivery.
"""

import json
import os
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


DEFAULT_ENDPOINT = "https://api.disseqt.ai/agentic-monitoring/api/v1/traces"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class LocalTransport:
    mode = "local"

    def __init__(self, directory="traces"):
        self.directory = Path(directory)

    def send(self, payload):
        self.directory.mkdir(parents=True, exist_ok=True)
        run_id = payload["traces"][0]["traceId"]
        # IDs are generated internally, never user-supplied file paths.
        if not all(char in "0123456789abcdef-" for char in run_id):
            raise ValueError("Invalid trace ID")
        with (self.directory / f"{run_id}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, allow_nan=False) + "\n")


class LiveTransport:
    mode = "live"

    def __init__(self, api_key, project_id, endpoint=DEFAULT_ENDPOINT, timeout=10):
        if not api_key or not project_id:
            raise ValueError("Live Disseqt transport requires API key and project ID")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")):
            raise ValueError("Disseqt endpoint must use HTTPS (HTTP allowed for loopback tests)")
        if not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("Invalid Disseqt endpoint")
        self.api_key, self.project_id, self.endpoint, self.timeout = api_key, project_id, endpoint, timeout

    def send(self, payload):
        wire = deepcopy(payload)
        # SDK 0.8.0 agentic ingestion embeds credentials in resource attributes;
        # validator APIs also use these headers. Never mutate the local payload.
        wire["resource"]["attributes"].update({"api.key": self.api_key, "project.id": self.project_id,
                                               "ingestion_url": self.endpoint})
        request = Request(self.endpoint, data=json.dumps(wire, allow_nan=False).encode(), method="POST",
                          headers={"Content-Type": "application/json", "X-API-Key": self.api_key,
                                   "X-Project-Id": self.project_id})
        with build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
            response.read()


class DisseqtClient:
    def __init__(self, run_id, *, local=None, remote=None, service_name="mortgage-capital-uc1", project_id="local", application_id=None):
        self.run_id, self.root_id = run_id, str(uuid4())
        self.local = local if local is not None else LocalTransport()
        self.remote, self.service_name, self.project_id = remote, service_name, project_id
        self.application_id = application_id
        self.spans, self.delivery_errors = [], []
        self.started_ms = time.time_ns() // 1_000_000

    def emit(self, name, kind="AGENT_EXEC", *, status="success", started_ms=None, duration_ms=0, attributes=None, parent=None, span_id=None):
        start = started_ms if started_ms is not None else time.time_ns() // 1_000_000
        span = {"traceId": self.run_id, "spanId": span_id or str(uuid4()),
                "parentSpanId": self.root_id if parent is None else parent,
                "name": name, "spanKind": kind, "startTimeMs": start,
                "endTimeMs": start + max(0, round(duration_ms)),
                "status": "OK" if status == "success" else "ERROR", "attributes": attributes or {}}
        resource = {"service.name": self.service_name, "service.version": "0.1.0",
                    "deployment.environment": "local-poc", "project.id": self.project_id}
        if self.application_id:
            resource["uc1.application_id"] = self.application_id
        payload = {"resource": {"attributes": resource}, "traces": [{"traceId": self.run_id, "spans": [span]}]}
        self.local.send(payload)
        if self.remote is not None:
            try:
                self.remote.send(payload)
            except Exception:
                # Network errors can contain URLs or credentials. Preserve a safe
                # delivery finding while retaining the full local audit.
                self.delivery_errors.append({"span_id": span["spanId"], "message": "Disseqt delivery failed; local trace retained"})
        self.spans.append({"name": name, "kind": kind, "status": status,
                           "started_ms": start, "duration_ms": duration_ms, "span_id": span["spanId"],
                           "attributes": deepcopy(attributes or {})})

    @contextmanager
    def step(self, name, kind="AGENT_EXEC", attributes=None):
        start, timer = time.time_ns() // 1_000_000, time.perf_counter()
        status = "success"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            self.emit(name, kind, status=status, started_ms=start,
                      duration_ms=(time.perf_counter() - timer) * 1000, attributes=attributes)

    def model_call(self, call):
        from datetime import datetime
        usage = call.get("usage") or {}
        self.emit(call["operation"], "MODEL_EXEC", status=call["status"],
                  started_ms=round(datetime.fromisoformat(call["started_at"]).timestamp() * 1000),
                  duration_ms=call["latency_ms"], attributes={
                      "gen_ai.system": call["provider"], "gen_ai.request.model": call["model"],
                      "gen_ai.usage.input_tokens": usage.get("prompt_tokens"),
                      "gen_ai.usage.output_tokens": usage.get("completion_tokens"),
                      "uc1.call": deepcopy(call),
                  })

    def finish(self, status="success"):
        self.emit("reconciliation_run", status=status, started_ms=self.started_ms,
                  duration_ms=time.time_ns() // 1_000_000 - self.started_ms,
                  span_id=self.root_id, parent="", attributes={"agentic.agent.name": "mortgage-capital-uc1"})


def get_client(run_id, *, directory="traces", environ=None):
    env = os.environ if environ is None else environ
    mode = env.get("DISSEQT_TRANSPORT", "local")
    if mode not in ("local", "live"):
        raise ValueError("DISSEQT_TRANSPORT must be local or live")
    remote = LiveTransport(env.get("DISSEQT_API_KEY"), env.get("DISSEQT_PROJECT_ID"),
                           env.get("DISSEQT_ENDPOINT", DEFAULT_ENDPOINT)) if mode == "live" else None
    return DisseqtClient(run_id, local=LocalTransport(directory), remote=remote,
                        project_id=env.get("DISSEQT_PROJECT_ID", "local"),
                        service_name=env.get("DISSEQT_SERVICE_NAME", "mortgage-capital-uc1"),
                        application_id=env.get("DISSEQT_APPLICATION_ID"))
