"""Local-only FastAPI dashboard and UC1 API. No credentials required."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.disseqt_wire import get_client
from app.engine import CANONICAL_FIELDS, FILE_KINDS
from app.graph import Pipeline
from app.providers import DEFAULT_OLLAMA_MODEL, ProviderConfigurationError, get_provider
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


def create_app(*, storage=None, environ=None, provider_factory=None):
    trace_directory = ROOT / "traces" if storage is None else Path(storage).parent / "traces"
    storage = Path(storage) if storage is not None else ROOT / "tmp" / "runs"
    env = dict(os.environ if environ is None else environ)
    runs, registry_lock = {}, Lock()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="uc1-run")
    baseline = None

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title="Mortgage Capital · Reconciliation", version="0.1.0", lifespan=lifespan)
    app.state.runs = runs

    def find(run_id):
        with registry_lock:
            run = runs.get(run_id)
        if run is None:
            raise HTTPException(404, "Run not found; runs are held in memory until server restart")
        return run

    @app.get("/health")
    def health():
        return {"status": "ok", "default_provider": env.get("LLM_PROVIDER", "mock"),
                "ollama_model": env.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                "openai_configured": bool(env.get("OPENAI_API_KEY")),
                "trace_mode": env.get("DISSEQT_TRANSPORT", "local"),
                "canonical_fields": CANONICAL_FIELDS}

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
