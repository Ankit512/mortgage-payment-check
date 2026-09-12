# Mortgage payment check — demo stack

One Compose file runs **FastAPI + LangGraph + Qwen**. OpenAI is not used.
The browser hits a single address. Ollama stays on the private Docker network.

```text
http://127.0.0.1:8080
        │
        ▼
   FastAPI dashboard / API / chat
        │
        ▼
   LangGraph  (always)
     ingest → Qwen mapping → human interrupt
     → code reconciliation → Qwen classify/draft → emit
        │
        ▼
   Ollama  ·  hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M
```

LangGraph owns the paused mapping checkpoint. Qwen is the only model: mapping,
classification, rationale and chat routing. Arithmetic stays in code.

## Run it

Docker Desktop (or another Docker Engine) and about **8 GB RAM**. The first
start downloads roughly **2.8 GB** of model weights and keeps them in a volume.

```sh
docker compose up --build
```

Open **http://127.0.0.1:8080**.

1. Example files → Use these files  
2. Confirm the column labels  
3. Confirm & check payments  
4. Ask about this check → “What’s on this screen?”

Stop with `Ctrl+C`, or `docker compose down`. Weights stay in `qwen-models`
until `docker compose down -v`.

## What this is

Synthetic one-month payment records. **LangGraph** pauses until you confirm
column labels, then the engine does the arithmetic. **Qwen** proposes the
mapping and drafts explanations. Amounts on screen come from the files. No
OpenAI key is used.

This is a single-process demo. Restarts clear in-memory checks. It is not a
multi-user product and it is not hosted on Vercel — Vercel cannot keep this
graph or the model.

## Optional: public URL without moving the model to Vercel

The `optional/vercel/` folder is a stateless gateway for a later public site.
It still needs this stack (or an equivalent host) as `UC1_WORKER_URL`. Prefer
this compose file for a walkthrough.
