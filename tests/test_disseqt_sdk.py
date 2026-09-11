import atexit
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from disseqt_agentic_sdk import DisseqtAgenticClient, start_trace
from disseqt_agentic_sdk.api.helpers import trace_llm_call, trace_tool_call
from disseqt_sdk import Client, SDKConfigInput
from disseqt_sdk.models.rag_grounding import RagGroundingRequest
from disseqt_sdk.validators.rag_grounding.faithfulness import FaithfulnessValidator
from fastapi.testclient import TestClient

from app.disseqt_sdk import SDKTransport
from app.disseqt_wire import DisseqtClient, LocalTransport, get_client
from app.main import create_app
from app.providers import DEFAULT_OLLAMA_MODEL
from scripts.sdk_capture import LocalSDKCapture


def sdk_environment(capture):
    return {"DISSEQT_TRANSPORT": "sdk", "DISSEQT_API_KEY": "local-sdk-placeholder",
            "DISSEQT_PROJECT_ID": "local-sdk-project", "DISSEQT_ENDPOINT": capture.endpoint}


class SDKTests(unittest.TestCase):
    def test_actual_high_level_sdk_client_and_helpers_accept_qwen_attribution(self):
        # Contract fixture counts, not a claim that a real model ran in this unit test.
        with LocalSDKCapture() as capture:
            client = DisseqtAgenticClient(api_key="local-sdk-placeholder", project_id="local-sdk-project",
                                          service_name="uc1-sdk-contract-test", endpoint=capture.endpoint,
                                          max_retries=0, max_batch_size=100, flush_interval=.05)
            try:
                with start_trace(client, "uc1") as trace:
                    with trace.start_span("reconciliation_run", "AGENT_EXEC") as root:
                        with trace_tool_call(trace, "reconcile_engine", "reconcile_engine"):
                            pass
                        with trace_llm_call(trace, "draft_rationale", model_name=DEFAULT_OLLAMA_MODEL,
                                            provider="ollama", input_tokens=50, output_tokens=12,
                                            input_messages=[{"role": "user", "content": "contract fixture"}]) as model:
                            model_id, parent_id = model.span_id, root.span_id
                client.flush()
                spans = capture.spans()
                self.assertEqual(len(spans), 3)
                model = next(span for span in spans if span["spanId"] == model_id)
                self.assertEqual(model["parentSpanId"], parent_id)
                attrs = model["attributes"]
                self.assertEqual(attrs["agentic.provider.name"], "ollama")
                self.assertEqual(attrs["agentic.request.model"], DEFAULT_OLLAMA_MODEL)
                self.assertEqual(attrs["agentic.usage.total_tokens"], 62)
            finally:
                client.shutdown()
                client.transport.session.close()
                atexit.unregister(client.shutdown)

    def test_sdk_adapter_preserves_all_source_spans_and_sdk_semantic_fields(self):
        with LocalSDKCapture() as capture, tempfile.TemporaryDirectory() as d:
            client = get_client(str(uuid4()), directory=d, environ=sdk_environment(capture))
            self.addCleanup(client.remote.close)
            client.emit("mapping_confirmed")
            client.emit("reconcile_engine", "TOOL_EXEC")
            call = {"operation": "draft_rationale", "provider": "ollama", "model": DEFAULT_OLLAMA_MODEL,
                    "started_at": datetime.now(timezone.utc).isoformat(), "latency_ms": 123.4,
                    "status": "success", "usage": {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62},
                    "input_messages": [{"role": "user", "content": "fixture"}],
                    "output_messages": [{"role": "assistant", "content": "fixture result"}]}
            original = deepcopy(call)
            client.model_call(call)
            client.finish()
            self.assertEqual(call, original)
            local_text = (Path(d) / f"{client.run_id}.jsonl").read_text()
            local = [json.loads(line)["traces"][0]["spans"][0] for line in local_text.splitlines()]
            self.assertEqual(local, capture.spans())
            attrs = local[2]["attributes"]
            self.assertEqual(attrs["agentic.usage.total_tokens"], 62)
            self.assertEqual(attrs["agentic.provider.name"], "ollama")
            self.assertNotIn("local-sdk-placeholder", local_text)
            self.assertEqual(client.delivery_errors, [])

    def test_sdk_http_failure_and_redirect_fail_visibly_without_retry(self):
        for status in (401, 500, 307):
            with self.subTest(status=status), LocalSDKCapture() as capture, tempfile.TemporaryDirectory() as d:
                capture.trace_status = status
                client = get_client(str(uuid4()), directory=d, environ=sdk_environment(capture))
                try:
                    client.emit("reconcile_engine", "TOOL_EXEC")
                    self.assertEqual(len(capture.requests), 1)
                    self.assertEqual(len(client.delivery_errors), 1)
                    self.assertTrue((Path(d) / f"{client.run_id}.jsonl").exists())
                finally:
                    client.remote.close()

    def test_sdk_unknown_token_usage_stays_unknown(self):
        with LocalSDKCapture() as capture, tempfile.TemporaryDirectory() as d:
            client = get_client(str(uuid4()), directory=d, environ=sdk_environment(capture))
            try:
                client.model_call({"operation": "classify", "provider": "ollama", "model": DEFAULT_OLLAMA_MODEL,
                    "started_at": datetime.now(timezone.utc).isoformat(), "latency_ms": 1,
                    "status": "error", "usage": None, "input_messages": [], "output_messages": []})
                self.assertIsNone(capture.spans()[0]["attributes"]["agentic.usage.total_tokens"])
                self.assertEqual(capture.spans()[0]["status"], "ERROR")
            finally:
                client.remote.close()

    def test_whole_fastapi_graph_pipeline_reaches_the_real_sdk_transport(self):
        with LocalSDKCapture() as capture, tempfile.TemporaryDirectory() as d:
            with TestClient(create_app(storage=Path(d)/"runs", environ=sdk_environment(capture))) as api:
                run = api.post("/runs", json={"provider": "mock"}).json()
                self.assertEqual(run["status"], "awaiting_confirmation")
                self.assertNotIn("reconcile_engine", [span["name"] for span in capture.spans()])
                run = api.post(f"/runs/{run['run_id']}/confirm", json={"mapping":run["proposed_mapping"]}).json()
                self.assertEqual(run["trace_mode"], "sdk-local")
                self.assertEqual(len(run["remediation_log"]), 12)
                spans = capture.spans()
                self.assertEqual(sum(span["spanKind"] == "MODEL_EXEC" for span in spans), 27)
                self.assertEqual(sum(span["name"] == "validate_and_policy" for span in spans), 12)
                self.assertEqual(api.get(f"/runs/{run['run_id']}/analytics").json()["delivery_errors"], [])

    def test_actual_validation_sdk_serializes_request_and_reads_explicit_server_fixture(self):
        with LocalSDKCapture() as capture:
            # Tests the client contract ONLY. This is not a hosted validator score.
            fixture = {"score": 0.25, "category": "faithfulness", "passed": False,
                       "label": "Fail", "details": {"test_fixture": True}}
            capture.validator_response = fixture
            client = Client(project_id="local-sdk-project", api_key="local-sdk-placeholder", base_url=capture.base_url)
            result = client.validate(FaithfulnessValidator(
                data=RagGroundingRequest(prompt="Explain the exception", context="Scheduled 1000", response="Scheduled 9999"),
                config=SDKConfigInput(threshold=1.0)))
            request = capture.requests[0]
            self.assertEqual(request["path"], "/api/v1/sdk/validators/rag-grounding/faithfulness")
            self.assertEqual(request["headers"]["X-API-Key"], "local-sdk-placeholder")
            self.assertEqual(request["body"]["input_data"]["llm_output"], "Scheduled 9999")
            self.assertEqual(result["score"], 0.25)

    def test_sdk_factory_never_invents_credentials_for_public_endpoint(self):
        with self.assertRaises(ValueError):
            get_client(str(uuid4()), environ={"DISSEQT_TRANSPORT": "sdk"})
        with self.assertRaises(ValueError):
            SDKTransport("placeholder", "project", "http://public.example/traces")


if __name__ == "__main__":
    unittest.main()
