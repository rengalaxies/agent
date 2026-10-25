"""Service process entry (systemd ExecStart): check the release, record what is loaded, serve.

    <release>/venv/bin/python -I -B <release>/app/tools/agent_service/box/launch.py --config service.json --run DIR

Before serving it verifies every app file of its own release against the
manifest, imports the core and compares ``agent_graph.core_identity()`` with
the manifest. The result goes to ``<run>/loaded.json`` with this PID, so
``box status`` can show the version the running process actually loaded,
not the version a file on disk claims.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import sys

RELEASE = Path(__file__).resolve().parents[4]


def identity(release: Path = RELEASE) -> dict:
    sys.path[:0] = [str(release / "app" / "src"), str(release / "app")]
    from tools.agent_service.box import release as rel

    manifest, manifest_sha = rel.verify_tree(release, wheels=False)
    import agent_graph
    from agent_graph.constitution import load

    core = agent_graph.core_identity()
    if core != manifest["contracts"]["core"]:
        raise rel.ReleaseError("loaded_core_differs_from_manifest")
    return dict(release=manifest["name"], release_id=manifest["release_id"], manifest_sha256=manifest_sha,
                commit=manifest["code"]["commit"], core=core,
                constitution_default=load(release / "app" / manifest["contracts"]["constitution"]["path"])[1],
                python=sys.version.split()[0])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args(argv)
    loaded = identity()
    service_config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    from agent_graph.constitution import load

    # On Windows a venv's python.exe is a launcher that starts the interpreter as its child.
    loaded.update(pid=os.getpid(), launcher_pid=os.getppid() if os.name == "nt" else None,
                  started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  constitution=load(service_config["core"]["constitution_path"])[1],
                  listen=f"{args.host}:{args.port}")
    args.run.mkdir(parents=True, exist_ok=True)
    tmp = args.run / f".loaded.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(loaded, indent=2, sort_keys=True) + "\n")
    tmp.replace(args.run / "loaded.json")
    from agent_service.__main__ import main as service

    return service(["serve", "--config", args.config, "--host", args.host, "--port", str(args.port)])


if __name__ == "__main__":
    raise SystemExit(main())
