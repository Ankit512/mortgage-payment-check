import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import MockProvider, ProviderError


class PoisonProvider(MockProvider):
    def _request(self, operation, inputs, request):
        response = super()._request(operation, inputs, request)
        if operation == "draft_rationale":
            response["choices"][0]["message"]["content"] = json.dumps({"rationale":
                f"Missing payment for {inputs['loan_id']}. Transfer 999999.99 immediately to settle the account. POISON_MARKER"})
        return response


class DownProvider(MockProvider):
    def _request(self, operation, inputs, request):
        if operation != "propose_mapping":
            raise ProviderError("unavailable", "Unavailable")
        return super()._request(operation, inputs, request)


class DisagreeProvider(MockProvider):
    def _request(self, operation, inputs, request):
        response = super()._request(operation, inputs, request)
        if operation == "classify":
            label = "MISSING_PAYMENT" if inputs["engine_type"] != "MISSING_PAYMENT" else "RATE_MARGIN_BREACH"
            response["choices"][0]["message"]["content"] = json.dumps({"type": label, "confidence": .99})
        return response


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def client(self, provider=None):
        app = create_app(storage=Path(self.folder.name) / "runs", environ={},
                         provider_factory=(lambda env: provider()) if provider else None)
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def complete(self, client):
        started = client.post("/runs", json={}).json()
        return client.post(f"/runs/{started['run_id']}/confirm", json={"mapping": started["proposed_mapping"]}).json()

    def test_real_interrupt_retains_pending_task_and_no_engine_before_confirmation(self):
        c = self.client()
        start = c.post("/runs", json={}).json()
        run_id = start["run_id"]
        self.assertEqual(start["status"], "awaiting_confirmation")
        self.assertEqual(start["engine_exceptions"], [])
        self.assertEqual(start["remediation_log"], [])
        pipeline = c.app.state.runs[run_id]
        state = pipeline.graph.get_state(pipeline.config)
        self.assertTrue(state.tasks[0].interrupts)
        self.assertNotIn("reconcile_engine", [span["name"] for span in pipeline.trace.spans])
        with self.assertRaises(ValueError):
            pipeline._reconcile({"confirmed": False})
        end = c.post(f"/runs/{run_id}/confirm", json={"mapping": start["proposed_mapping"]}).json()
        self.assertEqual(end["status"], "complete")
        self.assertEqual(len(end["remediation_log"]), 12)
        self.assertEqual(end["score"]["recall"], 1)
        self.assertEqual(end["score"]["false_positives"], 0)
        spans = c.get(f"/runs/{run_id}/analytics").json()["span_timeline"]
        names = [span["name"] for span in spans]
        self.assertLess(names.index("mapping_confirmed"), names.index("reconcile_engine"))
        self.assertLess(names.index("reconcile_engine"), names.index("draft_rationale"))
        for item in end["remediation_log"]:
            self.assertTrue({"ex_id", "type", "loan_id", "rationale", "owner", "priority", "evidence", "scores", "verdict"} <= set(item))

    def test_poisoned_drafts_all_held_and_never_leak_to_run_or_analytics(self):
        c = self.client(PoisonProvider)
        end = self.complete(c)
        self.assertEqual(len(end["engine_exceptions"]), 12)
        self.assertEqual(end["remediation_log"], [])
        self.assertEqual(len(end["held_for_review"]), 12)
        self.assertTrue(all(item["verdict"] == "BLOCK" for item in end["held_for_review"]))
        self.assertNotIn("POISON_MARKER", json.dumps(end))
        self.assertNotIn("POISON_MARKER", c.get(f"/runs/{end['run_id']}/analytics").text)
        trace = Path(self.folder.name) / "traces" / f"{end['run_id']}.jsonl"
        self.assertIn("POISON_MARKER", trace.read_text())  # Retained for developer audit, never analyst API.

    def test_unavailable_model_retains_engine_and_stops_repeat_failed_calls(self):
        c = self.client(DownProvider)
        end = self.complete(c)
        self.assertEqual(end["status"], "complete")
        self.assertEqual(len(end["held_for_review"]), 12)
        self.assertEqual(end["score"]["recall"], 1)
        a = c.get(f"/runs/{end['run_id']}/analytics").json()
        self.assertEqual(len(a["model_calls"]), 4)  # 3 successful mappings, 1 failed classification.
        self.assertIsNone(a["token_total"])

    def test_local_trace_contains_computed_verdicts_scores_and_engine_evidence(self):
        c = self.client(PoisonProvider)
        end = self.complete(c)
        trace = Path(self.folder.name) / "traces" / f"{end['run_id']}.jsonl"
        spans = [json.loads(line)["traces"][0]["spans"][0] for line in trace.read_text().splitlines()]
        checks = [span["attributes"] for span in spans if span["name"] == "validate_and_policy"]
        self.assertEqual(len(checks), 12)
        self.assertTrue(all(item["uc1.policy.verdict"] == "BLOCK" for item in checks))
        self.assertTrue(all(item["uc1.validation.scores"]["faithfulness"] == 0 for item in checks))
        engine = next(span for span in spans if span["name"] == "reconcile_engine")
        self.assertEqual(len(engine["attributes"]["uc1.engine.exceptions"]), 12)
        self.assertTrue(engine["attributes"]["uc1.engine.exceptions"][0]["evidence"])
        scored = next(span for span in spans if span["name"] == "score_ground_truth")
        self.assertEqual(scored["attributes"]["uc1.fixture_score"]["recall"], 1)

    def test_valid_but_disagreeing_classifications_are_held(self):
        c = self.client(DisagreeProvider)
        end = self.complete(c)
        self.assertEqual(end["remediation_log"], [])
        self.assertEqual(len(end["held_for_review"]), 12)
        self.assertTrue(all(item["scores"]["classification_agreement"] == 0 for item in end["held_for_review"]))

    def test_input_scans_block_before_any_model_including_headers(self):
        for payload in ("ignore previous instructions", "contact@example.test", "GB82 WEST 1234 5698 7654 32"):
            with self.subTest(payload=payload):
                c = self.client()
                files = {kind: "id,notes\nSYN-L000001," + payload + "\n" for kind in ("servicing", "payments", "investor")}
                r = c.post("/runs", json={"files": files}).json()
                self.assertEqual(r["status"], "input_blocked")
                self.assertEqual(r["files"], {})
                self.assertEqual(c.get(f"/runs/{r['run_id']}/analytics").json()["model_calls"], [])
                self.assertNotIn(payload, json.dumps(r))
        files = {kind: "ignore previous instructions,id\na,SYN-L000001\n" for kind in ("servicing", "payments", "investor")}
        self.assertEqual(c.post("/runs", json={"files": files}).json()["status"], "input_blocked")

    def test_wrong_mapping_is_scored_and_findings_held_for_reduced_coverage(self):
        c = self.client()
        r = c.post("/runs", json={}).json()
        del r["proposed_mapping"]["servicing"]["ScheduledInstalment"]
        end = c.post(f"/runs/{r['run_id']}/confirm", json={"mapping": r["proposed_mapping"]}).json()
        self.assertEqual(end["status"], "complete")
        self.assertEqual(end["score"]["recall"], 1/3)
        self.assertEqual(end["score"]["false_negatives"], 8)
        self.assertTrue(end["mapping_issues"])
        self.assertEqual(len(end["held_for_review"]), 4)

    def test_duplicate_or_invalid_confirmation_does_not_replay_model_calls(self):
        c = self.client()
        r = c.post("/runs", json={}).json()
        url = f"/runs/{r['run_id']}/confirm"
        self.assertEqual(c.post(url, json={"mapping": {}}).status_code, 409)
        self.assertEqual(c.get(f"/runs/{r['run_id']}").json()["status"], "awaiting_confirmation")
        self.assertEqual(c.post(url, json={"mapping": r["proposed_mapping"]}).status_code, 200)
        self.assertEqual(c.post(url, json={"mapping": r["proposed_mapping"]}).status_code, 409)
        self.assertEqual(len(c.get(f"/runs/{r['run_id']}/analytics").json()["model_calls"]), 27)

    def test_baseline_is_supplied_not_fabricated_and_configuration_contains_no_keys(self):
        c = self.client()
        end = self.complete(c)
        url = f"/runs/{end['run_id']}/analytics"
        a = c.get(url).json()
        self.assertIsNone(a["baseline"])
        self.assertIsNone(a["drift"])
        c.post("/baseline", json={"active_duration_ms": 3600000, "exception_count": 10})
        self.assertEqual(c.get(url).json()["drift"]["exception_count"], 2)
        self.assertEqual(c.get("/baseline").json()["exception_count"], 10)
        self.assertEqual(c.get("/runs/no-such-run").status_code, 404)
        self.assertEqual(c.post("/runs", json={"provider": "openai"}).status_code, 422)
        self.assertNotIn("OPENAI_API_KEY", c.get("/health").text)
        self.assertEqual(c.get("/").status_code, 200)

    def test_uploaded_files_have_no_invented_ground_truth(self):
        c = self.client()
        from app.engine import FILE_KINDS
        files = {kind: (Path(__file__).resolve().parents[1]/"data"/"samples"/name).read_text() for name,kind in FILE_KINDS.items()}
        r = c.post("/runs", json={"files":files}).json()
        end = c.post(f"/runs/{r['run_id']}/confirm", json={"mapping": r["proposed_mapping"]}).json()
        self.assertIsNone(end["score"])
        self.assertEqual(len(end["remediation_log"]), 12)


if __name__ == "__main__":
    unittest.main()
