"""FastAPI synthetic-data dashboard and UC1 worker API."""

import os
import io
import json
import zipfile
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock, BoundedSemaphore
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.disseqt_wire import get_client
from app import chat
from app.engine import CANONICAL_FIELDS, FILE_KINDS
from app.graph import Pipeline
from app.providers import DEFAULT_OLLAMA_MODEL, CHAT_TOPICS, ProviderError, ProviderConfigurationError, get_provider
from data.generate_samples import generate_samples


ROOT = Path(__file__).resolve().parent.parent


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = 42
    n_loans: int = Field(default=40, ge=1, le=100)
    provider: Literal["mock", "ollama", "openai"] | None = None
    # Text uploads keep the API simple and avoid arbitrary server filesystem access.
    files: dict[str, str] | None = None
    synthetic_data: Literal[True] = True


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, dict[str, str]]


class BaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="Week-1 manual baseline", min_length=1, max_length=100)
    active_duration_ms: float = Field(ge=0, allow_inf_nan=False)
    exception_count: int = Field(ge=0)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=600)
    account_id: str | None = Field(default=None, min_length=1, max_length=100)
    currency: Literal["GBP", "EUR", "USD"] = "GBP"
    previous_topic: str | None = Field(default=None, max_length=30)


def create_app(*, storage=None, environ=None, provider_factory=None):
    env = dict(os.environ if environ is None else environ)
    if storage is None and env.get("UC1_STORAGE_ROOT"):
        storage = Path(env["UC1_STORAGE_ROOT"]) / "runs"
    trace_directory = ROOT / "traces" if storage is None else Path(storage).parent / "traces"
    storage = Path(storage) if storage is not None else ROOT / "tmp" / "runs"
    runs, registry_lock = {}, Lock()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="uc1-run")
    baseline = None
    chat_slot = BoundedSemaphore(1)
    worker_token = env.get("UC1_WORKER_TOKEN", "")
    if worker_token and len(worker_token) < 32:
        raise ValueError("UC1_WORKER_TOKEN must contain at least 32 characters")

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=True)
        for run in runs.values():
            if hasattr(run.trace.remote, "close"):
                run.trace.remote.close()

    app = FastAPI(title="Mortgage Capital · Reconciliation", version="0.1.0", lifespan=lifespan)
    app.state.runs = runs

    @app.middleware("http")
    async def worker_auth(request: Request, call_next):
        if worker_token and request.url.path != "/health":
            supplied = request.headers.get("authorization", "")
            if not secrets.compare_digest(supplied.encode(), ("Bearer " + worker_token).encode()):
                return JSONResponse({"detail": "Worker authentication required"}, status_code=401)
        response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def find(run_id):
        with registry_lock:
            run = runs.get(run_id)
        if run is None:
            raise HTTPException(404, "Run not found; runs are held in memory until server restart")
        return run

    @app.get("/health")
    def health():
        provider = env.get("LLM_PROVIDER", "mock")
        return {"status": "ok", "orchestration": "langgraph",
                "default_provider": provider,
                "llm": "qwen" if provider == "ollama" else provider,
                "ollama_model": env.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                "openai_configured": bool(env.get("OPENAI_API_KEY")),
                "trace_mode": env.get("DISSEQT_TRANSPORT", "local"),
                "canonical_fields": CANONICAL_FIELDS}

    def examples():
        catalog = ROOT / "data" / "scenarios" / "catalog.json"
        return json.loads(catalog.read_text()) if catalog.exists() else []

    def example_folder(example_id):
        entry = next((entry for entry in examples() if entry["id"] == example_id), None)
        if entry is None:
            raise HTTPException(404, "Example not found")
        return entry, ROOT / "data" / "scenarios" / entry["id"]

    @app.get("/examples")
    def list_examples():
        return examples()

    @app.get("/examples/{example_id}")
    def get_example(example_id: str):
        entry, folder = example_folder(example_id)
        return {"id": entry["id"], "title": entry["title"],
                "files": {kind: (folder / filename).read_text() for filename, kind in FILE_KINDS.items()}}

    @app.get("/examples/{example_id}/download")
    def download_example(example_id: str):
        entry, folder = example_folder(example_id)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename in (*FILE_KINDS, "README.md", "mapping.json", "expected.json"):
                archive.writestr(filename, (folder / filename).read_bytes())
        return Response(output.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{entry["id"]}-csv-pack.zip"'})

    @app.post("/runs")
    def start(body: RunRequest, background: bool = False):
        if body.files is not None:
            if set(body.files) != set(CANONICAL_FIELDS):
                raise HTTPException(422, "Supply CSV text for servicing, payments and investor")
            if any(not value.strip() or len(value.encode()) > 512_000 for value in body.files.values()):
                raise HTTPException(422, "Each CSV must be nonempty and at most 512 KB")
        mode_env = {**env, "LLM_PROVIDER": body.provider or env.get("LLM_PROVIDER", "mock")}
        run_id = str(uuid4())
        try:
            provider = provider_factory(mode_env) if provider_factory else get_provider(mode_env)
            trace = get_client(run_id, directory=trace_directory, environ=env)
        except (ProviderConfigurationError, ValueError) as error:
            raise HTTPException(422, str(error)) from None
        with registry_lock:
            if len(runs) >= 50:
                raise HTTPException(409, "Local PoC run limit reached; restart the server to clear in-memory runs")
            folder = storage / run_id
            folder.mkdir(parents=True, exist_ok=True)
            manifest = None
            if body.files is None:
                manifest = generate_samples(folder, seed=body.seed, n_loans=body.n_loans)
            else:
                for filename, kind in FILE_KINDS.items():
                    (folder / filename).write_text(body.files[kind], encoding="utf-8", newline="")
            paths = {kind: folder / filename for filename, kind in FILE_KINDS.items()}
            run = Pipeline(run_id, paths, provider, trace, manifest=manifest)
            runs[run_id] = run
        if background:
            executor.submit(run.start)
            return run.snapshot()
        return run.start()

    @app.post("/runs/{run_id}/confirm")
    def confirm(run_id: str, body: ConfirmRequest, background: bool = False):
        run = find(run_id)
        try:
            prepared = run.prepare_confirmation(body.mapping)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        if background:
            executor.submit(run.resume, prepared)
            return run.snapshot()
        return run.resume(prepared)

    @app.get("/runs")
    def list_runs():
        with registry_lock:
            snapshots = [run.snapshot() for run in runs.values()]
        return [{key: item[key] for key in ("run_id", "status", "created_at", "provider", "model", "progress")} for item in reversed(snapshots)]

    @app.get("/runs/{run_id}")
    def get_run(run_id: str):
        return find(run_id).snapshot()

    @app.get("/runs/{run_id}/analytics")
    def analytics(run_id: str):
        return find(run_id).analytics(baseline)

    @app.post("/runs/{run_id}/chat")
    def ask(run_id: str, body: ChatRequest):
        run = find(run_id)
        snapshot = run.snapshot()
        if snapshot["status"] not in ("explaining", "complete") or not (snapshot.get("payment_summary") or {}).get("available"):
            raise HTTPException(409, "Confirm the file labels and wait for the payment figures before asking about this check.")
        if not chat.question_allowed(body.question):
            raise HTTPException(422, "Ask about the sample payment figures without personal details or instructions to override the checks.")
        if body.previous_topic is not None and body.previous_topic not in CHAT_TOPICS:
            raise HTTPException(422, "Unsupported previous topic")
        try:
            account_id = chat.explicit_account(body.question,
                [a["loan_id"] for a in snapshot["payment_summary"]["accounts"]], body.account_id)
            if account_id and account_id not in {a["loan_id"] for a in snapshot["payment_summary"]["accounts"]}:
                raise ValueError("Choose an account from this check.")
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if not chat_slot.acquire(blocking=False):
            raise HTTPException(429, "Another question is being answered. Try again shortly.")
        trace = None
        try:
            # Chat never consumes OpenAI tokens. A practice run keeps its labelled mock router.
            mode = "mock" if snapshot["provider"] == "mock" else "ollama"
            mode_env = {**env, "LLM_PROVIDER": mode, "OLLAMA_TIMEOUT_SECONDS": "35"}
            provider = provider_factory(mode_env) if provider_factory else get_provider(mode_env)
            trace = get_client(str(uuid4()), directory=trace_directory / "chat", environ=env)
            trace.emit("chat_context", attributes={"run_id": run_id, "account_id": account_id})
            try:
                topic = chat.forced_topic(body.question)
                if topic is None:
                    topic = chat.classify_question(
                        body.question, body.previous_topic,
                        provider.route_question(body.question, body.previous_topic),
                    )
            finally:
                for call in provider.calls:
                    trace.model_call(call)
            result = chat.answer(snapshot, run.files, topic, account_id=account_id, currency=body.currency)
            result.update({"mode": "quick_guide" if mode == "mock" else "qwen", "model": provider.model,
                           "audit_id": trace.run_id})
            trace.emit("chat_answer", attributes={"topic": topic, "read_only": True, "citations": result["citations"]})
            trace.finish()
            return result
        except (ProviderError, ProviderConfigurationError):
            if trace:
                trace.finish("error")
            raise HTTPException(503, "The question assistant is unavailable. Payment figures and See details remain available; try again shortly.") from None
        finally:
            if trace and hasattr(trace.remote, "close"):
                trace.remote.close()
            chat_slot.release()

    @app.post("/baseline")
    def set_baseline(body: BaselineRequest):
        nonlocal baseline
        baseline = body.model_dump()
        return baseline

    @app.get("/baseline")
    def get_baseline():
        return baseline

    @app.get("/")
    def dashboard():
        return FileResponse(ROOT / "app" / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
    return app


app = create_app()
