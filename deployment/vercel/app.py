"""Stateless Vercel entrypoint. Long-running LangGraph/Qwen work stays on the worker."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ROUTES = {
    "GET": re.compile(rf"(?:health|runs|baseline|examples|examples/[a-z0-9_]+(?:/download)?|runs/{UUID}(?:/analytics)?)"),
    "POST": re.compile(rf"(?:runs|baseline|runs/{UUID}/(?:confirm|chat))"),
}
MAX_BODY = 4_000_000


def create_gateway(*, environ=None, transport=None, public=None):
    env = dict(os.environ if environ is None else environ)
    origin = env.get("UC1_WORKER_URL", "").rstrip("/")
    token = env.get("UC1_WORKER_TOKEN", "")
    parsed = urlsplit(origin)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    configured = bool(origin and len(token) >= 32 and parsed.hostname and
                      not (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path) and
                      (parsed.scheme == "https" or (local and parsed.scheme == "http" and not env.get("VERCEL"))))
    assets = Path(public) if public else Path(__file__).parent / "public"
    app = FastAPI(title="Mortgage payment app", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def cache_policy(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/")
    def dashboard():
        return FileResponse(assets / "index.html")

    if (assets / "static").exists():
        app.mount("/static", StaticFiles(directory=assets / "static"), name="static")

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def forward(path: str, request: Request):
        if not ROUTES[request.method].fullmatch(path):
            return JSONResponse({"detail": "Route not found"}, status_code=404)
        if not configured:
            return JSONResponse({"detail": "Connect the payment worker: set UC1_WORKER_URL and UC1_WORKER_TOKEN in the Vercel project."}, status_code=503)
        if request.method == "POST" and request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Open the payment app to submit this request"}, status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                return JSONResponse({"detail": "Request is too large; use the smaller sample CSV files"}, status_code=413)
        # The gateway must never keep a Vercel invocation open for an entire run.
        params = {"background": "true"} if request.method == "POST" and (path == "runs" or path.endswith("/confirm")) else {}
        try:
            async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(45, connect=5), follow_redirects=False) as client:
                async with client.stream(request.method, origin + "/" + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, content=bytes(body)) as upstream:
                    if upstream.status_code in (301, 302, 303, 307, 308, 401, 403):
                        return JSONResponse({"detail": "Payment worker connection needs attention"}, status_code=502)
                    data = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BODY:
                            return JSONResponse({"detail": "This result is too large to display through Vercel. Use a smaller sample check."}, status_code=502)
                    headers = {key: upstream.headers[key] for key in ("content-type", "content-disposition") if key in upstream.headers}
                    return Response(bytes(data), status_code=upstream.status_code, headers=headers)
        except httpx.TimeoutException:
            return JSONResponse({"detail": "The payment worker took too long to respond. Refresh the check before starting another."}, status_code=504)
        except httpx.HTTPError:
            return JSONResponse({"detail": "The payment worker is unavailable. Check its connection and try again."}, status_code=503)

    return app


app = create_gateway()
