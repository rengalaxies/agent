"""Bounded Cloud.ru Foundation Models qualification. No credential fallback."""
import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

BASE = "https://foundation-models.api.cloud.ru/v1"
TARGET = "Qwen/Qwen3-Coder-Next"
MAX_BYTES = 262144


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(path, key, payload=None):
    """One attempt, fixed origin, no redirects, bounded response and timeout."""
    req = urllib.request.Request(
        BASE + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    status = None
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
            status = response.status
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {"result": "RESPONSE_TOO_LARGE", "http_status": status}, None
        value = json.loads(raw)
        if not isinstance(value, dict):
            return {"result": "INVALID_RESPONSE", "http_status": status}, None
        return {"result": "HTTP_OK", "http_status": status}, value
    except urllib.error.HTTPError as exc:
        # Never read or serialize error bodies, headers, URLs or exception text.
        status = exc.code
        exc.close()
        return {"result": "HTTP_ERROR", "http_status": status}, None
    except (ValueError, UnicodeError):
        return {"result": "INVALID_RESPONSE", "http_status": status}, None
    except Exception:
        return {"result": "TRANSPORT_ERROR", "http_status": status}, None


def probe(mode, env, transport=request_json):
    key = env.get("CLOUDRU_FOUNDATION_API_KEY", "").strip()
    report = {
        "mode": mode, "target_model": TARGET,
        "configuration": {"foundation_key_present": bool(key)},
        "catalog": {"result": "NOT_RUN"},
        "generation": {"result": "NOT_RUN"},
        "grant_coverage": "UNVERIFIED", "tariffs_and_quotas": "UNVERIFIED",
        "limits": {"attempts_per_endpoint": 1, "timeout_seconds": 20,
                   "max_completion_tokens": 16, "max_response_bytes": MAX_BYTES},
    }
    if not key:
        report["result"] = "BLOCKED_MISSING_FOUNDATION_KEY"
        return report
    if mode == "preflight":
        report["result"] = "CONFIG_PRESENT_ACCESS_UNTESTED"
        return report
    if mode == "generate" and not (
        env.get("FM_BUDGET_APPROVED") == "true"
        and env.get("FM_GRANT_CONFIRMED") == "true"
    ):
        report["result"] = "BLOCKED_BUDGET_OR_GRANT_UNCONFIRMED"
        return report
    row, data = transport("/models", key)
    report["catalog"] = row
    if data is None:
        report["result"] = "BLOCKED_CATALOG"
        return report
    models = data.get("data")
    if not isinstance(models, list):
        row["result"] = "INVALID_CATALOG"
        report["result"] = "BLOCKED_CATALOG"
        return report
    available = any(isinstance(m, dict) and m.get("id") == TARGET for m in models)
    # Only emit our fixed model ID; arbitrary API content never enters reports.
    row["target_available"] = available
    report["result"] = "TARGET_LISTED_INFERENCE_UNTESTED" if available else "TARGET_NOT_LISTED"
    if mode != "generate" or not available:
        return report
    row, data = transport("/chat/completions", key, {
        "model": TARGET, "messages": [{"role": "user", "content": "Reply OK."}],
        "max_completion_tokens": 16, "stream": False,
    })
    report["generation"] = row
    valid = bool(data and data.get("model") == TARGET
                 and isinstance(data.get("choices"), list) and data["choices"])
    row["valid_target_response"] = valid
    report["result"] = "PASS_GENERATION" if valid else "BLOCKED_GENERATION"
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preflight", "catalog", "generate"), default="preflight")
    args = parser.parse_args()
    report = probe(args.mode, os.environ)
    safe = json.dumps(report, indent=2) + "\n"
    Path("foundation-models-report.json").write_text(safe)
    print(safe, end="")
    return 1 if report["result"].startswith(("BLOCKED", "TARGET_NOT")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
