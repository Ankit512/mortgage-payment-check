import tempfile
import time
import unittest
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from deployment.vercel.app import create_gateway
from scripts.bundle_vercel import bundle

TOKEN = "test-only-worker-token-" + "x" * 32
ROOT = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.worker = create_app(storage=Path(self.temp.name) / "runs", environ={"UC1_WORKER_TOKEN": TOKEN})
        self.enterContext(TestClient(self.worker))

    def gateway(self, **kw):
        app = create_gateway(environ={"UC1_WORKER_URL": "http://127.0.0.1:8000", "UC1_WORKER_TOKEN": TOKEN},
                             transport=httpx.ASGITransport(app=self.worker), **kw)
        return self.enterContext(TestClient(app))

    def wait(self, client, run_id, wanted):
        for _ in range(100):
            snapshot = client.get(f"/runs/{run_id}").json()
            if snapshot["status"] == wanted:
                return snapshot
            time.sleep(.01)
        self.fail(snapshot)

    def test_gateway_recreation_preserves_human_checkpoint_and_worker_job(self):
        client = self.gateway()
        started = client.post("/runs?background=false", json={}).json()
        run_id = started["run_id"]
        # A different gateway instance handles the next request, as with Vercel cold starts.
        second = self.gateway()
        pending = self.wait(second, run_id, "awaiting_confirmation")
        self.assertEqual(pending["engine_exceptions"], [])
        response = second.post(f"/runs/{run_id}/confirm", json={"mapping": pending["proposed_mapping"]})
        self.assertEqual(response.status_code, 200)
        done = self.wait(client, run_id, "complete")
        self.assertEqual(done["payment_summary"]["scheduled"], "66561.34")
        chat = second.post(f"/runs/{run_id}/chat", json={"question": "Why is there a shortfall?", "currency": "USD"})
        self.assertEqual(chat.status_code, 200)
        self.assertIn("$7,430.01", chat.text)
        self.assertEqual(chat.headers["cache-control"], "no-store")
        self.assertNotIn(TOKEN, chat.text)

    def test_worker_auth_route_allowlist_and_cross_site_posts(self):
        direct = TestClient(self.worker)
        self.assertEqual(direct.get("/health").status_code, 200)
        self.assertEqual(direct.get("/runs").status_code, 401)
        self.assertEqual(direct.post("/runs", json={}, headers={"Authorization": "Bearer wrong"}).status_code, 401)
        gateway = self.gateway()
        self.assertEqual(gateway.get("/runs").status_code, 200)
        for path in ("/api/chat", "/docs", "/traces/file", "/runs/not-a-uuid", "/https://evil.test"):
            self.assertEqual(gateway.get(path).status_code, 404)
        self.assertEqual(gateway.post("/runs", json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(gateway.post("/runs", content=b"x" * 4_000_001).status_code, 413)

    def test_missing_config_and_upstream_failures_do_not_leak_credentials(self):
        for env in ({}, {"UC1_WORKER_URL": "http://127.0.0.1:8000", "UC1_WORKER_TOKEN": TOKEN, "VERCEL": "1"}):
            response = TestClient(create_gateway(environ=env)).get("/runs")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(TOKEN, response.text)
        for status in (302, 401):
            transport = httpx.MockTransport(lambda request: httpx.Response(status, headers={"Location": "https://elsewhere.test"}))
            client = TestClient(create_gateway(environ={"UC1_WORKER_URL": "https://worker.example", "UC1_WORKER_TOKEN": TOKEN}, transport=transport))
            self.assertEqual(client.get("/runs").status_code, 502)

    def test_clean_bundle_is_a_single_compose_appliance(self):
        target, archive = bundle(Path(self.temp.name) / "bundle")
        (target / ".env").write_text("UC1_WORKER_TOKEN=PRIVATE_EXISTING_TOKEN")
        target, archive = bundle(target)
        self.assertIn("PRIVATE_EXISTING_TOKEN", (target / ".env").read_text())
        compose = (target / "compose.yaml").read_text()
        readme = (target / "README.md").read_text()
        self.assertIn("8080:8080", compose)
        self.assertIn("LLM_PROVIDER: ollama", compose)
        self.assertIn("hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M", compose)
        self.assertNotIn("11434:11434", compose)
        self.assertIn("langgraph==", (target / "requirements.txt").read_text())
        self.assertIn("from langgraph.graph import END, START, StateGraph",
                      (target / "app/graph.py").read_text())
        self.assertIn("http://127.0.0.1:8080", readme)
        self.assertIn("docker compose up --build", readme)
        self.assertEqual((target / "app/static/chat.js").read_bytes(), (ROOT / "app/static/chat.js").read_bytes())
        self.assertEqual(
            (target / "optional/vercel/public/static/chat.js").read_bytes(),
            (ROOT / "app/static/chat.js").read_bytes(),
        )
        with zipfile.ZipFile(archive) as zipped:
            names = zipped.namelist()
            self.assertFalse(any(part in name.split("/") for name in names for part in ("traces", "tmp", ".git", ".env", ".venv")))
            self.assertFalse(any(name.endswith((".gguf", ".jsonl")) for name in names))
            self.assertTrue(any(name.endswith("compose.yaml") for name in names))
        gateway = self.gateway(public=target / "optional/vercel/public")
        self.assertEqual(gateway.get("/").status_code, 200)
        self.assertEqual(gateway.get("/static/chat.js").status_code, 200)
        self.assertEqual(gateway.get("/examples/mixed_checks/download").status_code, 200)
