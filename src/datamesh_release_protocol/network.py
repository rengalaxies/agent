"""E4-N transport: isolated HTTP domain services and a fail-safe coordinator.

HTTP is intended for loopback smoke tests or private TLS-terminated deployment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .distributed import make_event
from .engine import scenario_snapshot_id
from .journal import EventJournal
from .models import Decision, Scenario, ValidationMode
from .validators import validate
from .loaders import load_baseline_policy


def _body(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _sign(key: str, value: dict) -> str:
    return hmac.new(key.encode(), _body(value), hashlib.sha256).hexdigest()


def serve(domain: str, host: str, port: int, key: str, policy_path: Path) -> None:
    if len(key) < 32 or not domain:
        raise ValueError("domain and secret key of at least 32 characters required")
    policy = load_baseline_policy(policy_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/verdict":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000:
                    raise ValueError("invalid body size")
                envelope = json.loads(self.rfile.read(length))
                request = envelope["request"]
                if not hmac.compare_digest(str(envelope["signature"]), _sign(key, request)):
                    raise ValueError("invalid signature")
                scenario = Scenario.model_validate(request["scenario"])
                if {item.consumer_domain for item in scenario.obligations} != {domain}:
                    raise ValueError("obligations must belong to this domain")
                if request["snapshot_id"] != request["full_snapshot_id"]:
                    raise ValueError("snapshot mismatch")
                if request["proposal_id"] != f"E4N:{request['run_id']}:{scenario.scenario_id}:V2":
                    raise ValueError("proposal mismatch")
                verdict = validate(scenario, ValidationMode.V2, policy)[0]
                event = make_event(request["proposal_id"], request["snapshot_id"], verdict)
                delay = float(request.get("delay_s", 0))
                if not 0 <= delay <= 10:
                    raise ValueError("invalid delay")
                if delay:
                    time.sleep(delay)
                result = {"event": event, "signature": _sign(key, event)}
                data = _body(result)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                self.send_error(400)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def _request(domain: str, url: str, key: str, request: dict, timeout_s: float) -> dict:
    payload = _body({"request": request, "signature": _sign(key, request)})
    req = Request(url.rstrip("/") + "/verdict", payload, {"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout_s) as reply:
        if reply.status != 200:
            raise ValueError(f"HTTP {reply.status}")
        envelope = json.loads(reply.read(1_000_001))
    event = envelope["event"]
    if event.get("domain_id") != domain or not hmac.compare_digest(str(envelope["signature"]), _sign(key, event)):
        raise ValueError("invalid response authentication")
    return event


def coordinate(scenario: Scenario, run_id: str, endpoints: dict[str, str],
               keys: dict[str, str], journal_path: Path, *, timeout_s: float,
               delays: dict[str, float] | None = None, duplicate: bool = False) -> dict:
    if not run_id or not 0 < timeout_s <= 60:
        raise ValueError("run_id and timeout between 0 and 60 seconds required")
    domains = frozenset(item.consumer_domain for item in scenario.obligations)
    if len(domains) != 3 or set(endpoints) != domains or set(keys) != domains or not all(len(key) >= 32 for key in keys.values()):
        raise ValueError("three endpoints and keys must match the consumer domains")
    proposal = f"E4N:{run_id}:{scenario.scenario_id}:V2"
    snapshot = scenario_snapshot_id(scenario)
    started = time.monotonic()
    errors: dict[str, str] = {}
    deadline = started + timeout_s
    with EventJournal(journal_path, proposal, snapshot, domains) as journal:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {}
            for domain in sorted(domains):
                isolated = scenario.model_copy(update={"obligations": [item for item in scenario.obligations if item.consumer_domain == domain]})
                request = {"run_id": run_id, "proposal_id": proposal, "snapshot_id": snapshot,
                           "full_snapshot_id": snapshot, "scenario": isolated.model_dump(mode="json"),
                           "delay_s": (delays or {}).get(domain, 0)}
                futures[pool.submit(_request, domain, endpoints[domain], keys[domain], request, timeout_s)] = domain
            for future in as_completed(futures):
                domain = futures[future]
                try:
                    event = future.result()
                    if time.monotonic() > deadline:
                        errors[domain] = "deadline_exceeded"
                        continue
                    journal.append(event)
                    if duplicate:
                        journal.append(event)
                except (HTTPError, URLError, TimeoutError, ValueError, KeyError, OSError) as exc:
                    errors[domain] = type(exc).__name__
        # A late or missing verdict can never turn a finalized review into ACCEPT.
        decision = journal.finalize()
        replay = journal.replay()
    return {"run_id": run_id, "scenario_id": scenario.scenario_id, "proposal_id": proposal,
            "snapshot_id": snapshot, "decision": decision.value,
            "received_domains": sorted(replay.received),
            "missing_domains": sorted(domains - replay.received.keys()),
            "duplicates": replay.duplicates, "invalid_events": replay.invalid,
            "conflicts": sorted(replay.conflicts), "transport_errors": errors,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "confirmatory": False}
