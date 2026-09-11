"""R3 contracts and failure paths; no live OpenAI requests or real credentials."""

import csv
import io
import json
import os
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.engine import CANONICAL_FIELDS, load_mapped, reconcile, score_against_ground_truth
from app.providers import (
    DEFAULT_MODEL, OPENAI_ENDPOINT, LLMProvider, MockProvider, OpenAIHTTPTransport,
    OpenAIProvider, ProviderConfigurationError, ProviderError, get_provider,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = {
    "ex_id": "MISSING_PAYMENT:2026-08:SYN-L000005",
    "ex_type": "MISSING_PAYMENT", "loan_id": "SYN-L000005",
    "detail": "Loan SYN-L000005: scheduled 2580.61 for 2026-08; net received 0.00 across 0 payment postings.",
    "evidence": [{
        "file": "/local/private/servicing_extract.csv", "row_number": 6,
        "raw_text": "SYN-L000005,2026-08,2580.61,1.76\n",
        "raw": {"LoanIdentifier": "SYN-L000005", "Period": "2026-08",
                "ScheduledInstalment": "2580.61", "ContractMarginPct": "1.76"},
    }],
}


def completion(result):
    return {
        "id": "chatcmpl-test", "model": DEFAULT_MODEL,
        "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(result), "refusal": None,
        }}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                  "prompt_tokens_details": {"cached_tokens": 3}},
    }


class ScriptedTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(deepcopy(request))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


class MockProviderTests(unittest.TestCase):
    def test_default_is_keyless_mock_even_when_an_unused_key_exists(self):
        with patch.dict(os.environ, {}, clear=True), patch("app.providers.build_opener", side_effect=AssertionError("network")):
            self.assertIsInstance(get_provider(), MockProvider)
            self.assertIsInstance(get_provider({"OPENAI_API_KEY": "unused-test-key"}), MockProvider)
            provider = get_provider()
            result = provider.classify(EXAMPLE["detail"], EXAMPLE["ex_type"])
            self.assertEqual(result, {"type": "MISSING_PAYMENT", "confidence": 0.95})

    def test_alias_mapping_leaves_unknown_and_ambiguous_names_unresolved(self):
        provider = MockProvider()
        headers = ["LOAN REF", "amount_received", "UnknownMoney", "IgnoredRate"]
        self.assertEqual(provider.propose_mapping(headers, ["loan_id", "received_amount"]), {
            "LOAN REF": "loan_id", "amount_received": "received_amount",
        })
        self.assertEqual(provider.propose_mapping(["Loan_ID", "LoanIdentifier", "Period"], ["loan_id", "period"]), {
            "Period": "period",
        })

    def test_mock_results_repeat_and_confidence_is_not_a_validator_score(self):
        provider = MockProvider()
        first = provider.draft_rationale(EXAMPLE)
        self.assertEqual(provider.draft_rationale(EXAMPLE), first)
        self.assertIn(EXAMPLE["detail"], first)
        self.assertIn("Remediation:", first)
        self.assertEqual(provider.classify(EXAMPLE["detail"], EXAMPLE["ex_type"]), {
            "type": "MISSING_PAYMENT", "confidence": 0.95,
        })
        for record in provider.calls:
            self.assertTrue(record["is_mock"])
            self.assertEqual(record["provider"], "mock")
            self.assertEqual(record["usage"], {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
            self.assertNotIn("scores", record)
            self.assertNotIn("verdict", record)

    def test_keyless_mapping_engine_and_drafting_smoke_preserves_engine_results(self):
        with patch.dict(os.environ, {}, clear=True), patch("app.providers.build_opener", side_effect=AssertionError("network")):
            provider = get_provider()
            tables = []
            for kind, filename in (("servicing", "servicing_extract.csv"), ("payments", "payments_file.csv"), ("investor", "investor_report.csv")):
                path = ROOT / "data/samples" / filename
                with path.open(newline="") as stream:
                    headers = next(csv.reader(stream))
                proposal = provider.propose_mapping(headers, CANONICAL_FIELDS[kind])
                # Explicit fixture mapping for this seam test, not the M5 graph checkpoint.
                tables.append(load_mapped(path, proposal))
                self.assertEqual(tables[-1].issues, [])
            found = reconcile(*tables)
            before = deepcopy(found)
            for exception in found:
                classification = provider.classify(exception["detail"], exception["ex_type"])
                rationale = provider.draft_rationale(exception)
                self.assertEqual(classification["type"], exception["ex_type"])
                self.assertIn(exception["detail"], rationale)
            self.assertEqual(found, before)
            manifest = json.loads((ROOT / "data/samples/ground_truth.json").read_text())
            score = score_against_ground_truth(found, manifest)
            self.assertEqual((score["recall"], score["false_positives"]), (1.0, 0))
            self.assertEqual(len(provider.calls), 27)
            self.assertEqual(sum(call["usage"]["total_tokens"] for call in provider.calls), 0)


class ProviderContractTests(unittest.TestCase):
    def test_both_providers_have_identical_public_output_shapes(self):
        transport = ScriptedTransport(
            completion({"mapping": {"LoanIdentifier": "loan_id", "Mystery": None}}),
            completion({"type": "MISSING_PAYMENT", "confidence": 0.83}),
            completion({"rationale": "Missing payment for SYN-L000005. Review the source records."}),
        )
        providers = [MockProvider(), OpenAIProvider(api_key="test-key", transport=transport)]
        shapes = []
        for provider in providers:
            self.assertIsInstance(provider, LLMProvider)
            mapping = provider.propose_mapping(["LoanIdentifier", "Mystery"], ["loan_id"])
            classification = provider.classify(EXAMPLE["detail"], EXAMPLE["ex_type"])
            rationale = provider.draft_rationale(EXAMPLE)
            shapes.append((mapping, {key: type(value).__name__ for key, value in classification.items()}, type(rationale).__name__))
            self.assertEqual(len(provider.calls), 3)
        self.assertEqual(shapes[0], shapes[1])
        self.assertEqual(set(providers[0].calls[0]), set(providers[1].calls[0]))

    def test_request_contract_and_usage_are_captured_for_every_real_provider_operation(self):
        transport = ScriptedTransport(
            completion({"mapping": {"LoanIdentifier": "loan_id"}}),
            completion({"type": "MISSING_PAYMENT", "confidence": 0.83}),
            completion({"rationale": "Review the zero net payment for SYN-L000005."}),
        )
        provider = OpenAIProvider(api_key="test-key", transport=transport)
        provider.propose_mapping(["LoanIdentifier"], ["loan_id"])
        provider.classify(EXAMPLE["detail"], EXAMPLE["ex_type"])
        provider.draft_rationale(EXAMPLE)
        for operation, request, record in zip(("propose_mapping", "classify", "draft_rationale"), transport.requests, provider.calls):
            self.assertEqual(request["model"], DEFAULT_MODEL)
            self.assertEqual(request["temperature"], 0)
            self.assertFalse(request["store"])
            self.assertGreater(request["max_completion_tokens"], 0)
            self.assertEqual(request["response_format"]["type"], "json_schema")
            self.assertTrue(request["response_format"]["json_schema"]["strict"])
            self.assertEqual(request["response_format"]["json_schema"]["name"], operation)
            self.assertIn("JSON", request["messages"][0]["content"])
            self.assertEqual(record["input_messages"], request["messages"])
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["usage"]["total_tokens"], 18)
            self.assertEqual(record["usage"]["prompt_tokens_details"]["cached_tokens"], 3)
            self.assertGreaterEqual(record["latency_ms"], 0)
            self.assertFalse(record["is_mock"])
            self.assertEqual(record["response_id"], "chatcmpl-test")
            self.assertEqual(record["finish_reason"], "stop")
            self.assertEqual(record["returned_model"], DEFAULT_MODEL)
        self.assertEqual(len({record["call_id"] for record in provider.calls}), 3)
        self.assertEqual(sum(r["usage"]["total_tokens"] for r in provider.calls), 54)
        self.assertNotIn("test-key", json.dumps(provider.calls))

    def test_drafting_sends_raw_evidence_without_local_paths_and_preserves_input(self):
        before = deepcopy(EXAMPLE)
        transport = ScriptedTransport(completion({"rationale": "Review the source records."}))
        provider = OpenAIProvider(api_key="test-key", transport=transport)
        provider.draft_rationale(EXAMPLE)
        payload = json.loads(transport.requests[0]["messages"][1]["content"])
        self.assertEqual(payload["evidence"], [EXAMPLE["evidence"][0]["raw"]])
        self.assertNotIn("/local/private/", json.dumps(provider.calls))
        self.assertEqual(EXAMPLE, before)

    def test_in_set_disagreement_and_ungrounded_prose_remain_available_for_later_validators(self):
        text = "  Missing payment for SYN-L000005: collect 999999.99 immediately.  "
        transport = ScriptedTransport(
            completion({"type": "RATE_MARGIN_BREACH", "confidence": 1}), completion({"rationale": text}),
        )
        provider = OpenAIProvider(api_key="test-key", transport=transport)
        result = provider.classify(EXAMPLE["detail"], EXAMPLE["ex_type"])
        self.assertEqual(result, {"type": "RATE_MARGIN_BREACH", "confidence": 1.0})
        self.assertEqual(provider.draft_rationale(EXAMPLE), text)
        self.assertEqual(EXAMPLE["ex_type"], "MISSING_PAYMENT")
        # Success means the response shape is valid, not a PASS policy verdict.
        self.assertTrue(all("verdict" not in record for record in provider.calls))

    def test_empty_header_list_is_an_empty_mapping_for_both_providers(self):
        for provider in (MockProvider(), OpenAIProvider(api_key="test-key", transport=ScriptedTransport(completion({"mapping": {}})))):
            self.assertEqual(provider.propose_mapping([], ["loan_id"]), {})

    def test_invalid_operation_inputs_fail_before_a_model_call(self):
        provider = MockProvider()
        invalid_calls = (
            lambda: provider.propose_mapping(["A", "A"], ["loan_id"]),
            lambda: provider.propose_mapping(["A"], []),
            lambda: provider.propose_mapping("A", ["loan_id"]),
            lambda: provider.classify("", "MISSING_PAYMENT"),
            lambda: provider.classify("detail", "INVENTED"),
            lambda: provider.draft_rationale({}),
            lambda: provider.draft_rationale({**EXAMPLE, "evidence": []}),
        )
        for call in invalid_calls:
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(provider.calls, [])


class OpenAIFailureTests(unittest.TestCase):
    def test_invalid_classification_outputs_are_rejected_and_recorded(self):
        results = (
            {"type": "INVENTED", "confidence": 0.5}, {"type": "MISSING_PAYMENT", "confidence": True},
            {"type": "MISSING_PAYMENT", "confidence": "0.5"}, {"type": "MISSING_PAYMENT", "confidence": -0.1},
            {"type": "MISSING_PAYMENT", "confidence": 1.1}, {"type": "MISSING_PAYMENT"},
            {"type": "MISSING_PAYMENT", "confidence": 0.5, "verdict": "PASS"},
        )
        for result in results:
            with self.subTest(result=result):
                provider = OpenAIProvider(api_key="test-key", transport=ScriptedTransport(completion(result)))
                with self.assertRaises(ProviderError) as caught:
                    provider.classify(EXAMPLE["detail"], EXAMPLE["ex_type"])
                self.assertEqual(caught.exception.code, "invalid_output")
                self.assertEqual(provider.calls[0]["status"], "error")
                self.assertEqual(provider.calls[0]["usage"]["total_tokens"], 18)
                self.assertEqual(json.loads(provider.calls[0]["output_messages"][0]["content"]), result)

    def test_invalid_mapping_outputs_are_not_repaired_or_guessed(self):
        bad_mappings = (
            {"A": "loan_id"}, {"A": "loan_id", "B": "loan_id"},
            {"A": "invented", "B": None}, {"A": ["loan_id"], "B": None},
            {"A": None, "B": None, "C": None},
        )
        for mapping in bad_mappings:
            with self.subTest(mapping=mapping):
                provider = OpenAIProvider(api_key="test-key", transport=ScriptedTransport(completion({"mapping": mapping})))
                with self.assertRaises(ProviderError):
                    provider.propose_mapping(["A", "B"], ["loan_id"])

    def test_malformed_json_duplicate_keys_nonfinite_and_wrong_shape_fail(self):
        contents = (
            "not json", '{"type": "MISSING_PAYMENT", "confidence":', "[]",
            '{"type":"MISSING_PAYMENT","type":"RATE_MARGIN_BREACH","confidence":0.5}',
            '{"type":"MISSING_PAYMENT","confidence":NaN}',
            '{"type":"MISSING_PAYMENT","confidence":1e999}',
        )
        for content in contents:
            with self.subTest(content=content):
                response = completion({})
                response["choices"][0]["message"]["content"] = content
                provider = OpenAIProvider(api_key="test-key", transport=ScriptedTransport(response))
                with self.assertRaises(ProviderError):
                    provider.classify(EXAMPLE["detail"], EXAMPLE["ex_type"])
                self.assertEqual(provider.calls[0]["output_messages"][0]["content"], content)

    def test_refusal_and_truncation_raise_even_if_content_looks_valid(self):
        for reason in ("refusal", "length", "content_filter", "tool_calls"):
            with self.subTest(reason=reason):
                response = completion({"type": "MISSING_PAYMENT", "confidence": 0.9})
                if reason == "refusal":
                    response["choices"][0]["message"]["refusal"] = "Cannot comply."
                else:
                    response["choices"][0]["finish_reason"] = reason
                provider = OpenAIProvider(api_key="test-key", transport=ScriptedTransport(response))
                with self.assertRaises(ProviderError) as caught:
                    provider.classify(EXAMPLE["detail"], EXAMPLE["ex_type"])
                self.assertEqual(caught.exception.code, "refusal" if reason == "refusal" else "incomplete")
                self.assertEqual(provider.calls[0]["usage"]["total_tokens"], 18)

    def test_empty_or_nonstring_rationale_is_rejected(self):
        for rationale in ("", "   ", None, 42):
            with self.subTest(rationale=rationale):
                provider = OpenAIProvider(api_key="test-key", transport=ScriptedTransport(completion({"rationale": rationale})))
                with self.assertRaises(ProviderError):
                    provider.draft_rationale(EXAMPLE)

    def test_missing_usage_stays_unknown_instead_of_becoming_zero(self):
        response = completion({"rationale": "Review the records."})
        del response["usage"]
        provider = OpenAIProvider(api_key="test-key", transport=ScriptedTransport(response))
        self.assertEqual(provider.draft_rationale(EXAMPLE), "Review the records.")
        self.assertIsNone(provider.calls[0]["usage"])

    def test_invalid_usage_is_preserved_in_raw_response_and_rejected(self):
        for usage in ({"prompt_tokens": -1, "completion_tokens": 7, "total_tokens": 6},
                      {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 100}):
            with self.subTest(usage=usage):
                response = completion({"rationale": "Review the records."})
                response["usage"] = usage
                provider = OpenAIProvider(api_key="test-key", transport=ScriptedTransport(response))
                with self.assertRaises(ProviderError):
                    provider.draft_rationale(EXAMPLE)
                self.assertEqual(provider.calls[0]["raw_response"]["usage"], usage)
                self.assertIsNone(provider.calls[0]["usage"])

    def test_transport_failure_records_an_error_without_retry_or_mock_fallback(self):
        for error in (ProviderError("unavailable", "OpenAI unavailable"), RuntimeError("sensitive transport text")):
            with self.subTest(error_type=type(error).__name__):
                transport = ScriptedTransport(error)
                provider = OpenAIProvider(api_key="test-key", transport=transport)
                with self.assertRaises(ProviderError):
                    provider.draft_rationale(EXAMPLE)
                self.assertEqual(len(transport.requests), 1)
                record = provider.calls[0]
                self.assertEqual(record["status"], "error")
                self.assertFalse(record["is_mock"])
                self.assertIsNone(record["usage"])
                self.assertEqual(record["output_messages"], [])
                self.assertNotIn("sensitive transport text", json.dumps(record))

    def test_invalid_completion_envelopes_are_recorded_as_failures(self):
        for response in (None, [], {}, {"choices": []}, {"choices": [{"message": None}]}):
            with self.subTest(response=response):
                provider = OpenAIProvider(api_key="test-key", transport=ScriptedTransport(response))
                with self.assertRaises(ProviderError):
                    provider.draft_rationale(EXAMPLE)
                self.assertEqual(provider.calls[0]["status"], "error")


class HTTPAndConfigurationTests(unittest.TestCase):
    def test_http_transport_posts_the_documented_endpoint_body_and_headers(self):
        transport = OpenAIHTTPTransport("unit-test-key", timeout=2)
        body = {"model": DEFAULT_MODEL, "messages": [], "temperature": 0}
        response = completion({"rationale": "Review records."})
        with patch.object(transport._opener, "open", return_value=io.BytesIO(json.dumps(response).encode())) as opened:
            self.assertEqual(transport(body), response)
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, OPENAI_ENDPOINT)
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer unit-test-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), body)
        self.assertEqual(opened.call_args.kwargs["timeout"], 2)
        redirect = next(handler for handler in transport._opener.handlers if hasattr(handler, "redirect_request"))
        self.assertIsNone(redirect.redirect_request(request, None, 302, "redirect", {}, "https://example.com"))

    def test_http_errors_timeouts_and_invalid_response_json_are_safe_failures(self):
        failures = (
            HTTPError(OPENAI_ENDPOINT, 401, "unit-test-key", {}, io.BytesIO(b"unit-test-key")),
            URLError("unit-test-key"), TimeoutError("unit-test-key"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                transport = OpenAIHTTPTransport("unit-test-key")
                with patch.object(transport._opener, "open", side_effect=failure), self.assertRaises(ProviderError) as caught:
                    transport({})
                self.assertNotIn("unit-test-key", str(caught.exception))
        transport = OpenAIHTTPTransport("unit-test-key")
        with patch.object(transport._opener, "open", return_value=io.BytesIO(b"not json")), self.assertRaises(ProviderError):
            transport({})

    def test_mode_key_model_and_timeout_configuration_are_explicit(self):
        for env in ({"LLM_PROVIDER": "unknown"}, {"LLM_PROVIDER": ""}, {"LLM_PROVIDER": "openai"},
                    {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "   "}):
            with self.subTest(env=env), self.assertRaises(ProviderConfigurationError):
                get_provider(env)
        provider = get_provider({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "chosen-model"})
        self.assertIsInstance(provider, OpenAIProvider)
        self.assertEqual(provider.model, "chosen-model")
        self.assertEqual(provider.calls, [])  # Construction makes no API request.
        for timeout in (0, -1, True, float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ProviderConfigurationError):
                OpenAIHTTPTransport("test-key", timeout)


if __name__ == "__main__":
    unittest.main()
