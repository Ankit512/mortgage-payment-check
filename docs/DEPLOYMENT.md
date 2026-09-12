# Packaging and optional Vercel gateway

The presentable package is **one Compose appliance**: dashboard, payment API and
Qwen behind **http://127.0.0.1:8080**. See [DEMO_STACK.md](DEMO_STACK.md).

```sh
make bundle
cd dist/mortgage-payment-app
docker compose up --build
```

Vercel cannot hold LangGraph run state or a 2.8 GB GGUF. Do not try to put Qwen
inside the Vercel function. The zip still includes `optional/vercel/` if you later
want a public hostname that *forwards* to this stack.

The model is `hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M` with Ollama 0.34.0.
Weights download into a Docker volume on first start. No OpenAI or Disseqt key is
needed. Hosting resources are still required; free model weights do not imply
free hosting.

## Optional Vercel gateway

Use this only when the Compose app already has a public HTTPS origin. The
browser still talks only to Vercel; Vercel forwards known payment routes with a
server-side token. Ollama stays private.

```sh
python3 -c 'import secrets; from pathlib import Path; p=Path(".env"); p.touch(mode=0o600, exist_ok=False); p.write_text("UC1_WORKER_TOKEN=" + secrets.token_urlsafe(48) + "\n")'
```

If `.env` already exists, keep the existing token. Put HTTPS in front of the
Compose **app** port (`8080`). Keep one replica: run state is in memory.
The named audit volume keeps CSVs and JSONL across restarts, but does not restore
interactive runs. A restart requires creating another check. This is a shared
synthetic-data demonstration, not a multi-user customer account service.

## Connect Vercel

Deploy the bundle's **`optional/vercel/` directory** as the project root. The included
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

Local gateway verification can use `http://127.0.0.1:8080` as the app origin.
HTTP origins are accepted only for loopback outside Vercel; deployed gateways
require HTTPS. The gateway needs no model weights, GPU, database or OpenAI SDK.

## What the assistant does

Use **Ask about this check** once payment figures are available. It can summarise
the payment position, explain shortfalls/excess receipts, discuss each of the
three finding types, and identify source records to review. The selected account
and currency apply to the conversation. It supports short topic follow-ups;
changing the run, account or display currency clears the conversation.

Questions about the current page are answered from the confirmed payment
summary (totals, charts, finding counts). Narrow questions still use a topic
label; amounts always come from records, not from Qwen. Out-of-scope advice
is refused. An unavailable model does not switch to OpenAI.

Chat has no mapping-approval, payment or record-editing tools. It never uses held
rationales. Its model call and citation trail have a separate chat audit ID;
the original reconciliation snapshot and its metrics remain unchanged.

## Verification status

Verified on 12 September 2026:

- Automated backend tests pass, including a gateway instance changing
  between create/confirm/read/chat requests, worker authentication, request limits,
  source citations, rejected model prose, and secret-free one-box bundle regeneration.
- Browser acceptance passes for currency switching/persistence, chat scope,
  tutorial, mapping approval, all six CSV upload packs and mobile layouts.
- Real Qwen completed the 40-account check in 216.68 seconds: 12 findings,
  10 accepted explanations and 2 held. Six chat topics passed with actual Qwen,
  taking 1.0–2.5 seconds each. These are local observations, not cloud estimates.
- Vercel CLI 59.16.0 built the FastAPI project successfully for Python 3.13,
  with a 60-second gateway duration. Project `ank8/mortgage-payment-check` exists.
- Docker Compose configuration validates and the Ollama 0.34.0 image tag exists
  for Linux amd64/arm64. The recommended walkthrough is `docker compose up --build`
  and http://127.0.0.1:8080, not a Vercel-hosted model.

A public Vercel site still needs a reachable HTTPS origin for this stack.
Local/build success does not establish hosted-model performance.
