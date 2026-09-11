import json
import unittest

from app.providers import DEFAULT_OLLAMA_MODEL, OllamaProvider, ProviderError, get_provider


class OllamaTests(unittest.TestCase):
    def response(self, payload):
        return {"model":DEFAULT_OLLAMA_MODEL, "message":{"role":"assistant","content":json.dumps({"type":"MISSING_PAYMENT","confidence":.9})},
                "done":True, "done_reason":"stop", "prompt_eval_count":50, "eval_count":12}

    def test_ollama_uses_same_contract_with_native_schema_and_actual_counts(self):
        requests = []
        def transport(payload):
            requests.append(payload)
            return self.response(payload)
        p = OllamaProvider(transport=transport)
        self.assertEqual(p.classify("Loan SYN-L000001: missing payment", "MISSING_PAYMENT")["type"],"MISSING_PAYMENT")
        self.assertEqual(requests[0]["format"]["type"],"object")
        self.assertIs(requests[0]["think"],False)
        self.assertIs(requests[0]["stream"],False)
        self.assertEqual(requests[0]["model"], DEFAULT_OLLAMA_MODEL)
        self.assertEqual(p.calls[0]["usage"]["total_tokens"],62)
        self.assertIs(p.calls[0]["is_mock"],False)
        self.assertIn("ollama_response", p.calls[0]["raw_response"])

    def test_unfinished_response_fails_without_switching_to_mock(self):
        p = OllamaProvider(transport=lambda body:{**self.response(body),"done_reason":"length"})
        with self.assertRaises(ProviderError):
            p.classify("missing payment", "MISSING_PAYMENT")
        self.assertEqual(p.calls[0]["status"],"error")

    def test_missing_usage_remains_unknown(self):
        def transport(body):
            result = self.response(body)
            del result["eval_count"]
            return result
        p = OllamaProvider(transport=transport)
        p.classify("missing payment", "MISSING_PAYMENT")
        self.assertIsNone(p.calls[0]["usage"])

    def test_factory_and_local_endpoint_boundary(self):
        self.assertIsInstance(get_provider({"LLM_PROVIDER":"ollama"}),OllamaProvider)
        with self.assertRaises(ValueError):
            OllamaProvider(base_url="https://arbitrary.example")


if __name__ == "__main__":
    unittest.main()
