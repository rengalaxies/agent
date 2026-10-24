"""Reproducible loopback stand: real HTTP calls produce server access logs.

Orders and Inventory both serve GET /orders. Reporting calls Orders, Health
calls Inventory, Export (a consumer known from code) sends nothing. Each server
writes access-log-jsonl-1 segments and closes them with a coverage sidecar.

This proves the adapter reads logs born from real socket traffic. It does not
prove that any customer's log pipeline looks like this.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

INSTALLATION = "runtime-stand"
ENVIRONMENT = "stand"
SOURCE_ID = "stand-access-logs"
# Pod-like aliases exercise identity normalization; the mapping is operator config.
IDENTITIES = [
    dict(alias="orders-7f9c", service="orders"),
    dict(alias="inventory-2b1d", service="inventory"),
    dict(alias="reporting-5d8b", service="reporting"),
    dict(alias="Health", service="health"),
    dict(alias="export-0a4e", service="export"),
]


def stamp(moment=None):
    moment = moment or datetime.now(timezone.utc)
    return moment.isoformat(timespec="milliseconds")


class AccessLog:
    """One segment per emitter; the sidecar is written only on close (rotation)."""

    def __init__(self, directory: Path, emitter: str, started: datetime):
        self.path = directory / f"{emitter}-0001.jsonl"
        self.emitter, self.started = emitter, started
        self.lock = threading.Lock()
        self.stream = self.path.open("ab")

    def write(self, record):
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        with self.lock:
            self.stream.write(line)
            self.stream.flush()

    def close(self, ended: datetime):
        with self.lock:
            self.stream.close()
        sidecar = self.path.with_name(self.path.name[:-len(".jsonl")] + ".coverage.json")
        sidecar.write_text(json.dumps(dict(
            schema="access-log-segment-1", file=self.path.name, emitter=self.emitter,
            environment=ENVIRONMENT, start=stamp(self.started), end=stamp(ended), sample_rate=1.0,
            sha256=hashlib.sha256(self.path.read_bytes()).hexdigest()), indent=2))


def server(emitter: str, log: AccessLog, routes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received = datetime.now(timezone.utc)
            started = time.perf_counter()
            path = self.path.split("?", 1)[0]
            route = path if ("GET", path) in routes else None
            body = json.dumps(routes[("GET", path)]() if route else {"error": "not_found"}).encode()
            status = 200 if route else 404
            record = dict(ts=stamp(received), service=emitter, env=ENVIRONMENT,
                          method="GET", path=self.path, status=status,
                          duration_ms=round((time.perf_counter() - started) * 1000, 3))
            if route:
                record["route"] = route  # the framework's matched template, never the raw path
            client = self.headers.get("X-Client-Service")
            if client:
                record["client"] = client
            # Log before replying: the caller returns only after the line is on
            # disk, so closing the segment after the last call loses nothing.
            log.write(record)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def call(base_url, path, client=None):
    # No environment proxies: loopback traffic must not leave the machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(base_url + path, headers={"X-Client-Service": client} if client else {})
    try:
        with opener.open(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code


def run_stand(out: Path):
    """Run all calls once; return the source configuration and the window."""
    out = Path(out).resolve()
    logs = out / "access-logs"
    logs.mkdir(parents=True, exist_ok=False)
    # One shared coverage interval for every emitter, so the window has no seams.
    started = datetime.now(timezone.utc).replace(microsecond=0)
    orders_log = AccessLog(logs, "orders-7f9c", started)
    inventory_log = AccessLog(logs, "inventory-2b1d", started)
    orders = server("orders-7f9c", orders_log, {("GET", "/orders"): lambda: {"items": [1, 2], "next_cursor": None}})
    inventory = server("inventory-2b1d", inventory_log, {("GET", "/orders"): lambda: {"reorders": []}})
    orders_url = f"http://127.0.0.1:{orders.server_port}"
    inventory_url = f"http://127.0.0.1:{inventory.server_port}"
    calls = []

    def record(caller, callee, path, status):
        calls.append(dict(caller=caller, callee=callee, path=path, status=status))

    try:
        # Reporting -> Orders GET /orders, the positive edge from the shared example.
        for day in ("2026-10-22", "2026-10-23", "2026-10-24"):
            record("reporting", "orders", "/orders", call(orders_url, f"/orders?day={day}", "reporting-5d8b"))
        # Reporting -> Orders on an unknown path: a service edge with no route.
        record("reporting", "orders", "/missing", call(orders_url, "/missing", "reporting-5d8b"))
        # Health -> Inventory GET /orders: same path, different service.
        for _ in range(2):
            record("health", "inventory", "/orders", call(inventory_url, "/orders", "Health"))
        # An operator's manual request without caller identity: traffic, no edge.
        record(None, "orders", "/orders", call(orders_url, "/orders"))
    finally:
        for httpd in (orders, inventory):
            httpd.shutdown()
            httpd.server_close()
        # Timestamps are written with millisecond precision; round the end up so
        # the last record stays inside [start, end).
        ended = datetime.now(timezone.utc) + timedelta(milliseconds=1)
        orders_log.close(ended)
        inventory_log.close(ended)
    return dict(
        source=dict(id=SOURCE_ID, installation_id=INSTALLATION, environment=ENVIRONMENT, root=str(logs),
                    identities=IDENTITIES, instrumented_services=["orders", "inventory"]),
        window=dict(start=stamp(started), end=stamp(ended)), calls=calls)


def summary(stand, result, assessments):
    from agent_graph.runtime_observations import relationships
    return dict(
        verified="stand only: loopback HTTP + local access logs; customer source not connected",
        calls=stand["calls"], source_status=result["source"]["status"],
        source_reasons=result["source"]["reasons"],
        edges=[dict(kind=e["kind"], caller=e["caller"], callee=e["callee"],
                    operation=e["operation"] and f'{e["operation"]["method"]} {e["operation"]["route"]}',
                    requests=e["bases"][0]["aggregates"]["request_count"]) for e in relationships(result)],
        unattributed=result["unattributed"], assessments=assessments)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="new directory for logs and the report")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from agent_graph.runtime_observations import AccessLogSource, assess, read_access_logs
    stand = run_stand(args.out)
    result = read_access_logs(AccessLogSource.model_validate(stand["source"]),
                              stand["window"]["start"], stand["window"]["end"])
    assessments = [assess(result, "reporting", "orders", "GET", "/orders"),
                   assess(result, "export", "orders", "GET", "/orders"),
                   assess(result, "reporting", "inventory", "GET", "/orders")]
    report = summary(stand, result, assessments)
    (args.out / "observations.json").write_text(json.dumps(result, indent=2))
    (args.out / "summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
