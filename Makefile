PYTHON ?= .venv/bin/python
PORT ?= 8765
OLLAMA_BASE_URL ?= http://127.0.0.1:11434

.PHONY: install test serve dashboard demo sdk-demo vercel-bundle
vercel-bundle:
	$(PYTHON) -m scripts.bundle_vercel
install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m unittest discover tests -v

serve:
	$(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT)

dashboard:
	LLM_PROVIDER=ollama $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT)

# Actual Qwen inference + official SDK, with dummy credentials to loopback only.
sdk-demo:
	$(PYTHON) -m scripts.sdk_smoke --ollama-url $(OLLAMA_BASE_URL)

# Start a temporary mock server, exercise the checkpoint/API, then stop it.
demo:
	@set -eu; \
	LLM_PROVIDER=mock $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8766 > /tmp/uc1-demo-server.log 2>&1 & \
	uc1_demo_pid=$$!; \
	trap 'kill $$uc1_demo_pid 2>/dev/null || true' EXIT; \
	$(PYTHON) scripts/wait_for_api.py http://127.0.0.1:8766/health; \
	$(PYTHON) scripts/demo.py --url http://127.0.0.1:8766 --provider mock
