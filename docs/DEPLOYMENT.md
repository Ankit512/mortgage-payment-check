# Vercel application and Qwen companion

The bundle presents one website: dashboard, payment API, tutorial, example CSVs
and a payment-question assistant. It has two deployment targets:

| Target | Contents |
| --- | --- |
| `vercel/` | Static dashboard plus a stateless FastAPI API gateway |
| `worker/` | Existing FastAPI/LangGraph engine, audit files and an Ollama service that downloads the requested Qwen model |

The full reconciliation backend and model **run on the companion host**, not
inside Vercel. The browser uses only the Vercel origin. The gateway authenticates
to the companion using a server-side token and forwards only known payment API
routes. Model endpoints and worker credentials are never exposed to browser code.

This split keeps a human-paused graph and multi-minute model jobs on a continuous
process. Gateway requests submit work with `background=true` and poll its state;
the Vercel function does not start background threads or keep a run registry.
The model is `hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M` with Ollama 0.34.0.
Weights download into a Docker volume on first start. No OpenAI or Disseqt key is
needed. Hosting resources are still required; free model weights do not imply
free hosting.

Vercel documents bounded memory and invocation duration, a standard 500 MB Python
bundle limit, and a 5 GB large-functions beta. Even the larger package option
does not preserve this app's in-memory run state across function instances.
See [Vercel function limits](https://vercel.com/docs/functions/limitations),
[FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi), and
[Ollama Docker setup](https://docs.ollama.com/docker).

## Build the bundle

From the source repository:

```sh
make vercel-bundle
```

This creates `dist/mortgage-payment-app/` and `dist/mortgage-payment-app.zip`.
No `.env`, credentials, traces, virtual environments or downloaded model weights
are copied. The bundle includes frontend source, backend source and the exact
model download configuration.

## Start the companion

On a Docker host, enter the bundle's `worker/` directory. Generate a private token
into a local file, then start the services:

```sh
python3 -c 'import secrets; from pathlib import Path; p=Path(".env"); p.touch(mode=0o600, exist_ok=False); p.write_text("UC1_WORKER_TOKEN=" + secrets.token_urlsafe(48) + "\n")'
docker compose up --build -d
docker compose logs -f model-pull
```

If `.env` already exists, keep the existing token. The first model download is
about 2.8 GB. Allow additional RAM and disk for inference and container images;
the local model has been exercised on a 16 GB Mac, but Docker CPU performance
must be measured on the chosen host. Ollama has no public port in this Compose
file. The worker binds to `127.0.0.1:8000`.

Place the worker behind your host's HTTPS ingress/reverse proxy, forwarding to
that local port and retaining the `Authorization` header. Keep one worker process
and one replica: its run registry and LangGraph checkpoints are in memory.
The named audit volume keeps CSVs and JSONL across restarts, but does not restore
interactive runs. A restart requires creating another check. This is a shared
synthetic-data demonstration, not a multi-user customer account service.

## Connect Vercel

Deploy the bundle's **`vercel/` directory** as the project root. The included
`app.py`, pinned Python dependencies and `vercel.json` select the FastAPI runtime.
The `public/` directory contains the browser assets. Configure these two
server-side environment variables for the intended deployment environment:

| Variable | Value |
| --- | --- |
| `UC1_WORKER_URL` | The worker's HTTPS origin, with no path/query/credentials |
| `UC1_WORKER_TOKEN` | The same private token stored on the companion |

Then, from that directory with the Vercel CLI installed and signed in:

```sh
vercel deploy
```

Use Vercel Deployment Protection for the review URL and confirm its coverage
before sharing. All visitors permitted into this demo share the sample run
registry. [Vercel documents the protection options here](https://vercel.com/docs/deployment-protection).
The application loads without worker configuration and reports what connection
is missing; it does not fabricate successful payment results.

Local gateway verification can use `http://127.0.0.1:8000` as the worker URL.
HTTP origins are accepted only for loopback outside Vercel; deployed gateways
require HTTPS. The gateway needs no model weights, GPU, database or OpenAI SDK.

## What the assistant does

Use **Ask about this check** once payment figures are available. It can summarise
the payment position, explain shortfalls/excess receipts, discuss each of the
three finding types, and identify source records to review. The selected account
and currency apply to the conversation. It supports short topic follow-ups;
changing the run, account or display currency clears the conversation.

Qwen routes the question to a validated topic. Code then fills the answer from
the confirmed summary and original CSV line references. Qwen cannot supply
amounts, citations, account selections or final prose. This constrains the
assistant deliberately: unsupported questions receive a scope explanation,
not an invented answer. Topic routing can still misunderstand a question.
Quick-practice runs use a clearly labelled deterministic question router.
An unavailable or malformed Qwen response returns an explicit unavailable state
without switching to OpenAI or presenting a fake model answer.

Chat has no mapping-approval, payment or record-editing tools. It never uses held
rationales. Its model call and citation trail have a separate chat audit ID;
the original reconciliation snapshot and its metrics remain unchanged.

## Verification status

Verified on 11 September 2026:

- All 108 automated backend tests pass, including a gateway instance changing
  between create/confirm/read/chat requests, worker authentication, request limits,
  source citations, rejected model prose, and secret-free bundle regeneration.
- Browser acceptance passes for currency switching/persistence, chat scope,
  tutorial, mapping approval, all six CSV upload packs and mobile layouts.
- Real Qwen completed the 40-account check in 216.68 seconds: 12 findings,
  10 accepted explanations and 2 held. Six chat topics passed with actual Qwen,
  taking 1.0–2.5 seconds each. These are local observations, not cloud estimates.
- Vercel CLI 59.16.0 built the FastAPI project successfully for Python 3.13,
  with a 60-second gateway duration. Project `ank8/mortgage-payment-check` exists.
- Docker Compose configuration validates and the Ollama 0.34.0 image tag exists
  for Linux amd64/arm64. A container build was not run: the Docker daemon was off.

The project has not been deployed. The remaining connection is a reachable HTTPS
companion host and its private worker token. Local/build success does not
establish deployed Vercel runtime behavior or hosted-model performance.
