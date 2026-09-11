"""Run real local Qwen through FastAPI/LangGraph and the official Disseqt SDK.

Uses fixed dummy Disseqt credentials against an ephemeral loopback capture sink.
No hosted validator, account authentication or remote dashboard is exercised.
"""

import argparse
import json
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import DEFAULT_OLLAMA_MODEL
from scripts.sdk_capture import LocalSDKCapture


def run_smoke(*, ollama_url, output_dir, n_loans=40):
    output_dir.mkdir(parents=True, exist_ok=False)
    with LocalSDKCapture() as capture:
        env = {
            "LLM_PROVIDER": "ollama", "OLLAMA_MODEL": DEFAULT_OLLAMA_MODEL,
            "OLLAMA_BASE_URL": ollama_url,
            "DISSEQT_TRANSPORT": "sdk", "DISSEQT_ENDPOINT": capture.endpoint,
            "DISSEQT_API_KEY": "local-sdk-placeholder", "DISSEQT_PROJECT_ID": "local-sdk-project",
        }
        # Environment is constructed above; real credentials cannot be inherited.
        with TestClient(create_app(storage=output_dir/"runs", environ=env)) as api, patch(
            "app.providers.OpenAIProvider._request", side_effect=AssertionError("OpenAI is forbidden in this smoke test")
        ) as openai_calls:
            started = api.post("/runs", json={"seed":42, "n_loans":n_loans}).json()
            assert started["status"] == "awaiting_confirmation", started["error"]
            assert not started["mapping_errors"], started["mapping_errors"]
            assert not any(span["name"] == "reconcile_engine" for span in capture.spans())
            print("Qwen proposed mappings; graph is paused:", started["run_id"], flush=True)
            response = api.post(f"/runs/{started['run_id']}/confirm", json={"mapping":started["proposed_mapping"]})
            response.raise_for_status()
            run = response.json()
            analytics = api.get(f"/runs/{run['run_id']}/analytics").json()
            assert run["status"] == "complete", run["error"]
            assert run["score"]["recall"] == 1 and run["score"]["false_positives"] == 0
            assert not analytics["delivery_errors"], analytics["delivery_errors"]
            assert openai_calls.call_count == 0
            assert all(call["provider"] == "ollama" and not call["is_mock"] for call in analytics["model_calls"])

        spans = capture.spans()
        trace_file = output_dir/"traces"/f"{run['run_id']}.jsonl"
        local_text = trace_file.read_text()
        local = [json.loads(line)["traces"][0]["spans"][0] for line in local_text.splitlines()]
        assert spans == local, "SDK serialization changed trace content"
        assert "local-sdk-placeholder" not in local_text
        model_spans = [span for span in spans if span["spanKind"] == "MODEL_EXEC"]
        assert len(model_spans) == len(analytics["model_calls"])
        assert all(span["attributes"]["agentic.request.model"] == DEFAULT_OLLAMA_MODEL for span in model_spans)
        sdk_tokens = sum(span["attributes"]["agentic.usage.total_tokens"] or 0 for span in model_spans)
        assert sdk_tokens == analytics["known_token_total"]
        policy_spans = [span for span in spans if span["name"] == "validate_and_policy"]
        assert len(policy_spans) == len(run["engine_exceptions"])
        statuses = {item["ex_id"]:item["verdict"] for item in run["remediation_log"] + run["held_for_review"]}
        assert all(span["attributes"]["uc1.policy.verdict"] == statuses[span["attributes"]["uc1.ex_id"]] for span in policy_spans)
        with urlopen(ollama_url.rstrip("/") + "/api/version", timeout=5) as stream:
            runtime_version = json.load(stream)["version"]
        summary = {
            "run_id": run["run_id"], "model": DEFAULT_OLLAMA_MODEL, "ollama_version":runtime_version,
            "disseqt_sdk_version":version("disseqt-ai-sdk"), "seed":42, "n_loans":n_loans,
            "confirmation":"automated integration test; not owner review",
            "status":run["status"], "trace_mode":run["trace_mode"], "score":run["score"],
            "passed":len(run["remediation_log"]), "held":len(run["held_for_review"]),
            "held_findings":[{k:item[k] for k in ("loan_id","type","findings")} for item in run["held_for_review"]],
            "model_calls":len(model_spans), "token_total":analytics["token_total"], "sdk_recorded_tokens":sdk_tokens,
            "unknown_usage_calls":analytics["unknown_usage_calls"], "active_duration_ms":analytics["active_duration_ms"],
            "sdk_http_requests":len(capture.requests), "sdk_spans":len(spans), "policy_spans":len(policy_spans),
            "local_sdk_span_parity":True, "delivery_errors":analytics["delivery_errors"],
            "openai_calls":0, "real_credentials_used":False, "hosted_validator_execution":False,
            "disseqt_cloud_requests":0,
        }
        (output_dir/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        (output_dir/"sdk_requests.json").write_text(json.dumps(capture.requests, indent=2)+"\n")
        print(json.dumps(summary, indent=2), flush=True)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--n-loans", type=int, default=40, choices=range(3,101), metavar="3..100")
    parser.add_argument("--output-dir", type=Path, default=Path("tmp")/f"sdk-smoke-{uuid4()}")
    args = parser.parse_args()
    run_smoke(ollama_url=args.ollama_url, output_dir=args.output_dir, n_loans=args.n_loans)


if __name__ == "__main__":
    main()
