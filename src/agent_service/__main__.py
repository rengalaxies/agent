"""``python -m agent_service serve|reconcile|status --config service.yaml`` and ``python -m agent_service smoke``."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import threading

from .analysis import NotWiredAnalyzer
from .config import ServiceConfig, build, core_analyzer
from .service import Service


def _analyzer(spec: str | None, config: ServiceConfig):
    if spec:
        module, _, attr = spec.partition(":")
        return getattr(importlib.import_module(module), attr)()
    if config.core:
        return core_analyzer(config.core, code_version=config.analysis.get("code_version", "agent-service"))
    return NotWiredAnalyzer()


def _service(args) -> tuple[Service, ServiceConfig]:
    config = ServiceConfig.load(args.config)
    store, connectors, backends = build(config)
    service = Service(store=store, connectors=connectors, backends=backends,
                      analyzer=_analyzer(args.analyzer, config), installation_id=config.installation_id,
                      environment=config.environment, analysis_settings=config.analysis)
    return service, config


def worker_loop(service: Service, reconcile_seconds: float, stop: threading.Event) -> None:
    service.recover()
    service.reconcile()
    next_reconcile = service.store.clock() + reconcile_seconds
    while not stop.is_set():
        if service.store.clock() >= next_reconcile:
            service.reconcile()
            next_reconcile = service.store.clock() + reconcile_seconds
        if service.step() is None:
            stop.wait(0.5)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent_service")
    parser.add_argument("command", choices=["serve", "reconcile", "status", "smoke"])
    parser.add_argument("--config", help="service configuration (all commands except smoke)")
    parser.add_argument("--analyzer", help="trusted module:factory returning an Analyzer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--keep", help="smoke: keep the stand and state in this new directory")
    args = parser.parse_args(argv)
    if args.command == "smoke":
        from .smoke import main as smoke

        return smoke(args.keep)
    if not args.config:
        parser.error("--config is required")
    service, config = _service(args)
    if args.command == "status":
        print(json.dumps(service.store.status(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "reconcile":
        print(json.dumps(service.reconcile()))
        print(json.dumps(service.run_until_idle(10_000)))
        return 0
    import uvicorn

    from .api import create_app

    stop = threading.Event()
    worker = threading.Thread(target=worker_loop, args=(service, config.reconcile_seconds, stop), daemon=True)
    worker.start()
    try:
        uvicorn.run(create_app(service, status_token=os.environ.get("AGENT_SERVICE_STATUS_TOKEN")),
                    host=args.host, port=args.port, log_level="warning")
    finally:
        stop.set()
        worker.join(timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
