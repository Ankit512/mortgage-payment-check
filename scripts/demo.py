"""An explicit automated smoke test, not a record of owner mapping approval."""

import argparse
import json
from urllib.request import Request, urlopen


def request(base, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=900) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--provider", choices=("mock", "ollama", "openai"), default="mock")
    args = parser.parse_args()
    run = request(args.url, "/runs", {"provider": args.provider, "seed": 42, "n_loans": 40})
    print("Started:", run["run_id"], run["status"], flush=True)
    if run["status"] != "awaiting_confirmation" or run["mapping_errors"]:
        raise SystemExit("Mapping not ready; inspect the run in the dashboard")
    run = request(args.url, f"/runs/{run['run_id']}/confirm", {"mapping": run["proposed_mapping"]})
    analytics = request(args.url, f"/runs/{run['run_id']}/analytics")
    print(json.dumps({"run_id": run["run_id"], "status": run["status"], "score": run["score"],
                      "passed": len(run["remediation_log"]), "held": len(run["held_for_review"]),
                      "tokens": analytics["token_total"], "active_duration_ms": analytics["active_duration_ms"]}, indent=2))
    if run["status"] != "complete" or run["score"]["recall"] != 1 or run["score"]["false_positives"] != 0:
        raise SystemExit("Smoke test failed")


if __name__ == "__main__":
    main()
