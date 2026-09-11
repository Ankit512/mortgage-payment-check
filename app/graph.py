"""A real LangGraph interrupt separates proposed mappings from computation.

One Pipeline owns one graph/checkpointer/provider/audit trail. Runtime state is
in memory; local JSONL is an audit record, not a resumable job database.
"""

import csv
import time
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock, RLock
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app import validators
from app.engine import CANONICAL_FIELDS, load_mapped, reconcile, score_against_ground_truth
from app.providers import ProviderError


class GraphState(TypedDict, total=False):
    blocked: bool
    confirmed: bool
    mapping: dict


class Pipeline:
    def __init__(self, run_id, files, provider, trace, *, manifest=None):
        self.run_id, self.files, self.provider, self.trace = run_id, files, provider, trace
        self.manifest = manifest
        self._lock, self.execution_lock = RLock(), Lock()
        self._private_drafts = {}  # Not serialized by public API or analytics.
        self._data = {
            "run_id": run_id, "status": "created", "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": provider.provider_name, "model": provider.model,
            "trace_mode": getattr(trace.remote, "mode", "live") if trace.remote else "local", "synthetic": True,
            "proposed_mapping": {}, "confirmed_mapping": None, "files": {},
            "ingest_scores": {}, "ingest_findings": {}, "mapping_errors": [],
            "mapping_issues": [], "engine_exceptions": [], "remediation_log": [],
            "held_for_review": [], "score": None, "progress": {"completed": 0, "total": None},
            "error": None, "active_duration_ms": 0,
        }
        builder = StateGraph(GraphState)
        builder.add_node("ingest", self._ingest)
        builder.add_node("propose_mapping", self._propose)
        builder.add_node("human_checkpoint", self._checkpoint)
        builder.add_node("reconcile", self._reconcile)
        builder.add_node("classify_and_draft", self._explain)
        builder.add_node("emit", self._finish)
        builder.add_edge(START, "ingest")
        builder.add_conditional_edges("ingest", lambda state: "stop" if state["blocked"] else "go",
                                      {"stop": END, "go": "propose_mapping"})
        builder.add_edge("propose_mapping", "human_checkpoint")
        builder.add_edge("human_checkpoint", "reconcile")
        builder.add_edge("reconcile", "classify_and_draft")
        builder.add_edge("classify_and_draft", "emit")
        builder.add_edge("emit", END)
        self.graph = builder.compile(checkpointer=InMemorySaver())
        self.config = {"configurable": {"thread_id": run_id}}

    def _update(self, **values):
        with self._lock:
            self._data.update(deepcopy(values))

    def snapshot(self):
        with self._lock:
            return deepcopy(self._data)

    def _execute(self, action):
        timer = time.perf_counter()
        try:
            self.graph.invoke(action, config=self.config)
        except Exception as error:
            # Engine input errors are useful, but may contain raw submitted text.
            # Detailed diagnostics go to local audit, not public error strings.
            self.trace.emit("run_error", status="error", attributes={"error_type": type(error).__name__,
                                                                      "detail": str(error)[:2000]})
            self._update(status="error", error="Run failed. Check mapped values, CSV structure and the local audit trace.")
            self.trace.finish("error")
        finally:
            self._update(active_duration_ms=self.snapshot()["active_duration_ms"] + (time.perf_counter() - timer) * 1000)

    def start(self):
        with self.execution_lock:
            if self.snapshot()["status"] != "created":
                raise ValueError("Run has already started")
            self._execute({"blocked": False, "confirmed": False})
        return self.snapshot()

    def prepare_confirmation(self, mapping):
        """Validate and claim the paused run atomically before scheduling work."""
        with self._lock:
            if self._data["status"] != "awaiting_confirmation":
                raise ValueError("Run is not awaiting mapping confirmation")
            if set(mapping) != set(CANONICAL_FIELDS):
                raise ValueError("Supply mappings for servicing, payments and investor")
            for kind, fields in mapping.items():
                if not isinstance(fields, dict) or set(fields) - set(self._data["files"][kind]["headers"]):
                    raise ValueError("Mapping contains an unknown raw header")
                if any(value not in CANONICAL_FIELDS[kind] for value in fields.values()):
                    raise ValueError("Mapping contains an unknown canonical field")
                if len(set(fields.values())) != len(fields):
                    raise ValueError("Two columns cannot map to the same canonical field")
            self._data["status"] = "queued"
            return deepcopy(mapping)

    def resume(self, prepared_mapping):
        with self.execution_lock:
            if self.snapshot()["status"] != "queued":
                raise ValueError("Confirmation has not been prepared")
            self._execute(Command(resume={"mapping": prepared_mapping, "confirmed": True}))
        return self.snapshot()

    def confirm(self, mapping):
        return self.resume(self.prepare_confirmation(mapping))

    def _ingest(self, state):
        self._update(status="ingesting")
        attributes = {}
        with self.trace.step("ingest", attributes=attributes):
            records, previews = [], {}
            for kind, path in self.files.items():
                with self.trace.step("read_csv", "TOOL_EXEC", {"file_kind": kind}):
                    table = load_mapped(path, {}, kind=kind)
                    with open(path, encoding="utf-8-sig", newline="") as stream:
                        headers = next(csv.reader(stream))
                    records.extend(headers)
                    records.extend(row.source["raw"] for row in table.rows)
                    previews[kind] = {"filename": path.name, "headers": headers, "row_count": len(table.rows),
                                      "preview": [row.source["raw"] for row in table.rows[:3]]}
            checks = {}
            for name in ("injection_scan", "pii_scan"):
                with self.trace.step(name, "TOOL_EXEC"):
                    checks[name] = getattr(validators, name)(records)
            scores = {name: result[0] for name, result in checks.items()}
            findings = {name: result[1] for name, result in checks.items()}
            blocked = any(value < 1 for value in scores.values())
            attributes.update({"uc1.ingest.scores": scores, "uc1.ingest.findings": findings})
            self._update(ingest_scores=scores, ingest_findings=findings,
                         files={} if blocked else previews,
                         status="input_blocked" if blocked else "proposing_mapping")
        if blocked:
            self.trace.finish("error")
        return {"blocked": blocked}

    def _model(self, operation, *args):
        before = len(self.provider.calls)
        try:
            return getattr(self.provider, operation)(*args)
        finally:
            for call in self.provider.calls[before:]:
                self.trace.model_call(call)

    def _propose(self, state):
        mapping, errors = {}, []
        for kind in CANONICAL_FIELDS:
            try:
                mapping[kind] = self._model("propose_mapping", self.snapshot()["files"][kind]["headers"], list(CANONICAL_FIELDS[kind]))
            except ProviderError as error:
                mapping[kind] = {}
                errors.append({"file_kind": kind, "code": error.code,
                               "message": "Mapping proposal unavailable; map this file manually"})
            self._update(proposed_mapping=mapping, mapping_errors=errors)
        self._update(status="awaiting_confirmation")
        return {}

    def _checkpoint(self, state):
        # No side effects before interrupt: LangGraph restarts this node on resume.
        decision = interrupt({"run_id": self.run_id, "proposed_mapping": self.snapshot()["proposed_mapping"]})
        if decision.get("confirmed") is not True:
            raise ValueError("Human mapping confirmation is required")
        self.trace.emit("mapping_confirmed", attributes={"mapping": decision["mapping"]})
        self._update(confirmed_mapping=decision["mapping"], status="reconciling")
        return {"confirmed": True, "mapping": decision["mapping"]}

    def _reconcile(self, state):
        if state.get("confirmed") is not True or self.snapshot()["confirmed_mapping"] is None:
            raise ValueError("No confirmed mapping")
        attributes = {}
        with self.trace.step("reconcile_engine", "TOOL_EXEC", attributes):
            tables = [load_mapped(self.files[kind], state["mapping"][kind], kind=kind) for kind in CANONICAL_FIELDS]
            issues = [issue for table in tables for issue in table.issues]
            found = reconcile(*tables)
            attributes.update({"uc1.engine.exceptions": found, "uc1.mapping.issues": issues})
            self._update(engine_exceptions=found, mapping_issues=issues,
                         progress={"completed": 0, "total": len(found)})
        if self.manifest is not None:
            score_attributes = {}
            with self.trace.step("score_ground_truth", "TOOL_EXEC", score_attributes):
                score = score_against_ground_truth(found, self.manifest)
                score_attributes["uc1.fixture_score"] = score
                self._update(score=score)
        return {}

    def _explain(self, state):
        self._update(status="explaining")
        data = self.snapshot()
        passed, held, unavailable = [], [], False
        for index, exception in enumerate(data["engine_exceptions"], start=1):
            classification, rationale, error_code = {}, "", None
            try:
                if unavailable:
                    raise ProviderError("not_attempted", "Provider unavailable earlier in this run")
                classification = self._model("classify", exception["detail"], exception["ex_type"])
                rationale = self._model("draft_rationale", exception)
            except ProviderError as error:
                error_code = error.code
                unavailable = unavailable or error.code in ("unavailable", "http_error")
            attributes = {"uc1.ex_id": exception["ex_id"]}
            with self.trace.step("validate_and_policy", "TOOL_EXEC", attributes):
                checks = {
                    "faithfulness": validators.faithfulness(rationale, exception["evidence"], exception["detail"]),
                    "answer_relevance": validators.answer_relevance(rationale, exception["ex_type"], exception["loan_id"]),
                    "classification_in_set": validators.classification_in_set(classification),
                    "plan_coherence": validators.plan_coherence(self.trace.spans),
                    **{name: (score, data["ingest_findings"][name]) for name, score in data["ingest_scores"].items()},
                }
                scores = {name: result[0] for name, result in checks.items()}
                findings = {name: result[1] for name, result in checks.items() if result[1]}
                extras = {"provider_success": float(error_code is None),
                          "classification_agreement": float(classification.get("type") == exception["ex_type"]),
                          "mapping_complete": float(not data["mapping_issues"])}
                scores.update(extras)
                if error_code:
                    findings["provider_success"] = [f"Model step failed: {error_code}; deterministic evidence retained"]
                if not extras["classification_agreement"]:
                    findings["classification_agreement"] = ["Model classification does not agree with the engine"]
                if data["mapping_issues"]:
                    findings["mapping_complete"] = ["Incomplete mapping; detection coverage is reduced"]
                verdict = validators.apply_policy(scores, {**validators.DEFAULT_THRESHOLDS, **dict.fromkeys(extras, 1.0)})
                attributes.update({"uc1.validation.scores": scores, "uc1.validation.findings": findings,
                                   "uc1.policy.verdict": verdict, "uc1.engine_type": exception["ex_type"],
                                   "uc1.loan_id": exception["loan_id"]})
                item = {"ex_id": exception["ex_id"], "type": exception["ex_type"], "loan_id": exception["loan_id"],
                        "engine_detail": exception["detail"], "evidence": exception["evidence"],
                        "owner": "Unassigned", "priority": "High" if exception["ex_type"] != "RATE_MARGIN_BREACH" else "Medium",
                        "scores": scores, "findings": findings, "verdict": verdict}
                if verdict == "PASS":
                    passed.append({**item, "rationale": rationale})
                else:
                    self._private_drafts[exception["ex_id"]] = {"rationale": rationale, "classification": classification}
                    held.append(item)  # Never send blocked model prose to an analyst.
            self._update(remediation_log=passed, held_for_review=held, progress={"completed": index, "total": len(data["engine_exceptions"])})
        return {}

    def _finish(self, state):
        self.trace.emit("emit", attributes={"pass_count": len(self.snapshot()["remediation_log"]),
                                             "block_count": len(self.snapshot()["held_for_review"])})
        self.trace.finish()
        self._update(status="complete")
        return {}

    def analytics(self, baseline=None):
        data = self.snapshot()
        # Public summaries deliberately exclude raw model messages/responses.
        calls = [{key: deepcopy(call.get(key)) for key in (
            "call_id", "operation", "provider", "model", "is_mock", "status", "latency_ms", "usage", "error",
        )} for call in list(self.provider.calls)]
        items = data["remediation_log"] + data["held_for_review"]
        names = sorted({name for item in items for name in item["scores"]})
        means = {name: sum(item["scores"][name] for item in items) / len(items) for name in names}
        known_tokens = sum(call["usage"]["total_tokens"] for call in calls if call["usage"] is not None)
        unknown = sum(call["usage"] is None for call in calls)
        cost = 0.0 if self.provider.provider_name in ("mock", "ollama") else None
        current = {"active_duration_ms": data["active_duration_ms"], "exception_count": len(data["engine_exceptions"])}
        drift = None if baseline is None else {name: current[name] - baseline[name] for name in current}
        return {"span_timeline": [{key: deepcopy(span[key]) for key in ("name", "kind", "status", "started_ms", "duration_ms", "span_id")} for span in list(self.trace.spans)],
                "validator_means": means, "pass_count": len(data["remediation_log"]), "block_count": len(data["held_for_review"]),
                "model_calls": calls, "known_token_total": known_tokens, "unknown_usage_calls": unknown,
                "token_total": None if unknown else known_tokens,
                "estimated_api_cost_usd": cost, "cost_note": "Local compute cost excluded" if cost == 0 else "No model price configured",
                "active_duration_ms": data["active_duration_ms"], "baseline": baseline, "drift": drift,
                "delivery_errors": deepcopy(self.trace.delivery_errors)}
