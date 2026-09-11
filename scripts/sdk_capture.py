"""Loopback capture sink for SDK tests. This is not a Disseqt service emulator."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class LocalSDKCapture:
    def __init__(self):
        self.requests = []
        self.trace_status = 200
        self.validator_response = None  # Explicit response fixture required for contract tests.
        capture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/agentic-monitoring/api/v1/traces":
                    status, result = capture.trace_status, {"local_capture": True}
                elif self.path == "/api/v1/sdk/validators/rag-grounding/faithfulness" and capture.validator_response is not None:
                    status, result = 200, capture.validator_response
                else:
                    status, result = 404, {"local_capture": True, "error": "Unknown test route"}
                capture.requests.append({"path": self.path, "headers": dict(self.headers), "body": payload, "status": status})
                self.send_response(status)
                if status == 307:
                    self.send_header("Location", "/redirected-do-not-follow")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.endpoint = self.base_url + "/agentic-monitoring/api/v1/traces"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def spans(self):
        return [span for request in self.requests if request["path"] == "/agentic-monitoring/api/v1/traces"
                for trace in request["body"]["traces"] for span in trace["spans"]]
