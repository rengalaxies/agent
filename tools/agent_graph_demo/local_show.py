"""Local wrapper over existing authenticated UI and guarded operator runner. No deployment."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from agent_graph_demo.snapshots import atomic_json
from tools.agent_graph_demo.run_scenario import run
from tools.agent_graph_demo.runtime_guard import RuntimeGuard

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", required=True, type=Path)
    sub = p.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--image", required=True, help="immutable sha256 image ID")
    sub.add_parser("serve")
    runner = sub.add_parser("run")
    runner.add_argument("--session", required=True)
    runner.add_argument("--version", required=True, choices=list("ABDE"))
    sub.add_parser("stop")
    sub.add_parser("observe")
    args = p.parse_args()
    root = args.directory.resolve()
    config = root / "operator.json"
    if args.action == "init":
        if config.exists() or (root / "web.json").exists():
            p.error("configuration exists; reuse serve/run instead of erasing history")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (root / "state").mkdir(exist_ok=True, mode=0o700)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        operator = dict(state_root=str(root / "state"), runtime_root=str(root / "runtime"),
                        product_sha=sha, image=args.image)
        guard = RuntimeGuard(**operator)
        guard.reconcile(0)
        subprocess.run([sys.executable, "tools/agent_graph_demo/configure.py", "--directory", str(root),
                        "--product-sha", sha], check=True)
        atomic_json(config, operator)
        print("Ready; use serve then run in another terminal. MODEL OFF.")
        return
    operator = json.loads(config.read_text())
    if args.action == "serve":
        subprocess.run([sys.executable, "-m", "agent_graph_demo", "--config", str(root / "web.json")], check=True)
        return
    guard = RuntimeGuard(**operator)
    record = guard.read()
    if args.action == "run":
        receipt = run(operator, args.session, args.version, record["generation"], root / "receipts")
        print(json.dumps(dict(status=receipt["status"], version=receipt["version"],
                              consumers=receipt["consumers"]), ensure_ascii=False))
        return 2 if receipt["status"] == "ERROR" else 0
    elif args.action == "stop":
        guard.stop(record.get("session_id"), record["generation"])
        print("STOPPED; history preserved. UI reset can create the next show.")
    else:
        guard.refresh(record["generation"])
        print("Observation refreshed; this is not a new behavior check.")

if __name__ == "__main__":
    sys.exit(main())
