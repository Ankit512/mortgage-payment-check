import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from app.disseqt_wire import DisseqtClient, LiveTransport, LocalTransport, get_client


class TraceTests(unittest.TestCase):
    def test_captured_http_server_receives_same_spans_as_local_transport(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captured.append((dict(self.headers), body, self.path))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1",0), Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as d:
            run_id = str(uuid4())
            remote = LiveTransport("test-secret", "project-test", f"http://127.0.0.1:{server.server_port}/traces")
            client = DisseqtClient(run_id, local=LocalTransport(d),remote=remote,project_id="project-test")
            client.emit("ingest", "AGENT_EXEC")
            client.emit("mapping_confirmed", "AGENT_EXEC")
            client.emit("reconcile_engine", "TOOL_EXEC")
            client.emit("draft_rationale", "MODEL_EXEC",attributes={"agentic.usage.input_tokens":12})
            client.finish()
            text = (Path(d)/f"{run_id}.jsonl").read_text()
            local = [json.loads(line) for line in text.splitlines()]
            self.assertEqual(len(local),5)
            self.assertNotIn("test-secret",text)
            for record, (headers, wire, path) in zip(local,captured):
                self.assertEqual(record["traces"],wire["traces"])
                self.assertEqual(path,"/traces")
                self.assertEqual(headers["X-Api-Key"],"test-secret")
                self.assertEqual(headers["X-Project-Id"],"project-test")
                self.assertEqual(wire["resource"]["attributes"]["api.key"],"test-secret")
                self.assertNotIn("api.key",record["resource"]["attributes"])
            self.assertEqual(local[-1]["traces"][0]["spans"][0]["parentSpanId"],"")

    def test_delivery_failure_is_visible_and_local_audit_survives(self):
        class Down:
            def send(self, payload):
                raise RuntimeError("secret should not reach diagnostics")
        with tempfile.TemporaryDirectory() as d:
            client = DisseqtClient(str(uuid4()),local=LocalTransport(d),remote=Down())
            client.emit("ingest")
            self.assertEqual(len(client.delivery_errors),1)
            self.assertNotIn("secret",json.dumps(client.delivery_errors))
            self.assertEqual(len(list(Path(d).glob("*.jsonl"))),1)

    def test_live_selection_is_explicit_and_incomplete_config_fails(self):
        client = get_client(str(uuid4()),environ={"DISSEQT_API_KEY":"test-secret"})
        self.assertIsNone(client.remote)
        with self.assertRaises(ValueError):
            get_client(str(uuid4()),environ={"DISSEQT_TRANSPORT":"live"})
        with self.assertRaises(ValueError):
            LiveTransport("secret","project","http://example.test/traces")


if __name__ == "__main__":
    unittest.main()
