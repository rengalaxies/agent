"""Operator-only fixed sandbox lifecycle. No cloud or model access, no arbitrary commands."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

from agent_graph_demo.contracts import DemoError, now
from agent_graph_demo.snapshots import Snapshots, atomic_json
from tools.agent_graph_demo.state_access import StateAccess
from examples.agent_graph_demo.oracle import DATASET_BYTES, DATASET_SHA256, check_ids
from examples.agent_graph_demo.scenarios import sources
from tools.agent_graph_demo.runtime_guard import RuntimeGuard


def run(config, sid, version, expected_generation, output):
    sid = str(uuid.UUID(sid))
    guard = RuntimeGuard(
        config["state_root"],
        config["runtime_root"],
        config["image"],
        config["product_sha"],
    )
    store = StateAccess(config["state_root"])
    snapshots = Snapshots(config["state_root"], config["product_sha"])
    with guard.exclusive():
        s = store.session(sid)
        if s["pending_job_id"] or s["closed"]:
            raise DemoError("session_busy_or_closed")
        if s["scenario_version"] != version:
            raise DemoError("run_only_published_version")
        m = snapshots.manifest(sid, version)
        if (
            m["product_sha"] != config["product_sha"]
            or m["manifest_sha256"] != s["proposed_manifest_sha256"]
        ):
            raise DemoError("runtime_manifest_mismatch")
        source = snapshots.session_root(sid) / "snapshots" / version / "corpus"
        # Do not execute source selected by the web. Match every byte against this release's templates.
        actual = {
            str(f.relative_to(source)): f.read_text()
            for f in source.rglob("*")
            if f.is_file()
        }
        if actual != sources(version):
            raise DemoError("runtime_source_not_in_trusted_release")
        # Copy trusted release bytes into operator-owned runtime plan area to remove mutable web TOCTOU.
        dest = guard.root / "sources" / sid / m["manifest_sha256"]
        for name, text in sources(version).items():
            f = dest / "corpus" / name
            f.parent.mkdir(parents=True, exist_ok=True)
            if f.exists():
                if f.is_symlink() or f.read_text() != text:
                    raise DemoError("operator_snapshot_changed")
            else:
                f.write_text(text)
                f.chmod(0o444)
        for directory in [
            dest / "corpus",
            *(d for d in (dest / "corpus").rglob("*") if d.is_dir()),
        ]:
            directory.chmod(0o755)
        dataset = dest / "dataset.json"
        if dataset.exists():
            if dataset.is_symlink() or dataset.read_bytes() != DATASET_BYTES:
                raise DemoError("operator_dataset_changed")
        else:
            dataset.write_bytes(DATASET_BYTES)
            dataset.chmod(0o444)
        started = now()
        runtime = None
        receipt = dict(
            id=uuid.uuid4().hex,
            session_id=sid,
            session_revision=s["revision"],
            version=version,
            proposed_manifest_sha256=m["manifest_sha256"],
            running_manifest_sha256=None,
            dataset_sha256=DATASET_SHA256,
            fixed_check_id="collection",
            command_id="collection-v1",
            started_at=started,
            finished_at=None,
            origin="operator_runner",
            status="ERROR",
            graph_status="EXTERNAL_REPORTED",
            independently_verified=False,
            consumers={},
        )
        try:
            runtime = guard.activate_locked(
                sid, m, dest / "corpus", dataset, expected_generation
            )
            receipt["running_manifest_sha256"] = runtime["manifest_sha256"]
            receipt["runtime_stage"] = "CHECK"
            for name in ("reporting", "billing") + (
                ("export",) if version == "E" else ()
            ):
                receipt["consumers"][name.title()] = check_ids(
                    guard.consumer(runtime, name)["result"]
                )
            health = guard.consumer(runtime, "health")["result"]
            if health != {"status": "available", "service": "Status"}:
                raise DemoError("status_negative_control_failed")
            receipt["health_control"] = health
            receipt["status"] = (
                "PASS"
                if all(c["passed"] for c in receipt["consumers"].values())
                else "FAIL"
            )
            receipt["exit_code"] = 0 if receipt["status"] == "PASS" else 1
        except Exception as exc:
            receipt["runtime_stage"] = "CHECK" if runtime else "STARTUP"
            receipt["error_code"] = (
                exc.code if isinstance(exc, DemoError) else "runner_failed"
            )
            receipt["exit_code"] = 2
        receipt["finished_at"] = now()
        receipt["runtime_generation"] = guard.read()["generation"]
        receipt["artifact_sha256"] = hashlib.sha256(
            json.dumps(receipt, sort_keys=True).encode()
        ).hexdigest()
        output = Path(output)
        atomic_json(output / (receipt["id"] + ".json"), receipt)
        # Runner uses the same workload lock, but does not claim the graph independently verified its report.
        store.artifact(sid, "receipt", receipt)
        return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("run", "stop", "observe", "reconcile"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--expected-generation", type=int, required=True)
        if name in ("run", "stop"):
            cmd.add_argument("--session", required=True)
        if name == "run":
            cmd.add_argument("--version", choices=["A", "B", "D", "E"], required=True)
            cmd.add_argument("--check", choices=["collection"], required=True)
            cmd.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        c = json.loads(args.config.read_text())
        if args.command == "run":
            result = run(
                c, args.session, args.version, args.expected_generation, args.output
            )
        else:
            g = RuntimeGuard(
                c["state_root"], c["runtime_root"], c["image"], c["product_sha"]
            )
            if args.command == "stop":
                result = g.stop(str(uuid.UUID(args.session)), args.expected_generation)
            else:
                result = getattr(
                    g, "refresh" if args.command == "observe" else "reconcile"
                )(args.expected_generation)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result.get("status") == "ERROR" else 0
    except (DemoError, ValueError, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "code": exc.code
                    if isinstance(exc, DemoError)
                    else "operator_config_or_state_error",
                }
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
