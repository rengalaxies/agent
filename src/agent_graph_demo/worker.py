"""One installation worker; recovery restores files before releasing reservations."""

import threading
import time

from .contracts import DemoError
from .locks import locked


def citations(value):
    if isinstance(value, dict):
        if {"source_id", "start_line", "end_line", "quote"} <= value.keys():
            yield {
                k: value[k] for k in ("source_id", "start_line", "end_line", "quote")
            }
        else:
            for v in value.values():
                yield from citations(v)
    elif isinstance(value, list):
        for v in value:
            yield from citations(v)


class Worker:
    def __init__(self, store, snapshots, cli, seconds=180, hook=None):
        self.store, self.snapshots, self.cli, self.seconds = (
            store,
            snapshots,
            cli,
            seconds,
        )
        self.stop = threading.Event()
        self.hook = hook

    def recover(self):
        with locked(self.store.root / "workload.lock"):
            for j in self.store.running():
                s = self.store.session(j["session_id"])
                if (
                    s["pending_job_id"] != j["id"]
                    or s["revision"] != j["session_revision"]
                ):
                    raise DemoError("recovery_conflict")
                self.snapshots.materialize(s["id"], s["scenario_version"])
                self.store.finish(
                    j, "UNKNOWN_AFTER_RESTART", error="interrupted_no_automatic_retry"
                )

    def run_once(self):
        # Acquire workload before claim so operator work does not consume job deadline.
        with locked(self.store.root / "workload.lock"):
            j = self.store.claim()
            if j is None:
                return False
            deadline = time.monotonic() + self.seconds
            cancelled = (
                lambda: self.stop.is_set()
                or self.store.job(j["id"])["cancel_requested"]
            )
            s = self.store.session(j["session_id"])
            root = self.snapshots.session_root(s["id"])
            kwargs = dict(deadline=deadline, cancelled=cancelled)

            def call(command, **extra):
                return self.cli.invoke(root, command, **kwargs, **extra)

            try:
                if cancelled():
                    raise DemoError("cancelled")
                if (
                    s["pending_job_id"] != j["id"]
                    or s["revision"] != j["session_revision"]
                ):
                    raise DemoError("reservation_lost")
                manifest = self.snapshots.materialize(
                    s["id"], j["target_version"] or s["scenario_version"]
                )
                if self.hook:
                    self.hook("materialized", j)
                p = j["payload"]
                if j["action"] == "prepare_context":
                    graph = call("prepare_context", task=p.get("task", ""))
                    result = graph
                elif j["action"] == "analyze_change":
                    result = call("analyze_change", context=p["base_context_id"])
                    graph = call("dependencies", context=result["context_used_id"])
                elif j["action"] == "propose":
                    # Bind the core audit actor to authenticated server identity, never browser fields.
                    import json
                    from .snapshots import atomic_json

                    policy = json.loads((root / "policy.json").read_text())
                    policy["subject"] = j["actor"]
                    atomic_json(root / "policy.json", policy)
                    result = call(
                        "propose", context=p["context_id"], message=p["proposal"]
                    )
                    graph = call("dependencies", context=p["context_id"])
                else:
                    raise DemoError("model_unavailable")
                graph["demo_version"] = manifest["scenario_version"]
                seen = {}
                from .contracts import canonical

                for citation in citations([graph, result]):
                    key = canonical(citation)
                    if key not in seen:
                        evidence_context = graph["context_id"]
                        try:
                            evidence = call(
                                "evidence", context=evidence_context, message=citation
                            )
                        except DemoError as exc:
                            if exc.code != "not_found" or not p.get("base_context_id"):
                                raise
                            evidence_context = p["base_context_id"]
                            evidence = call(
                                "evidence", context=evidence_context, message=citation
                            )
                        evidence_version = manifest["scenario_version"]
                        if evidence_context != graph["context_id"]:
                            evidence_version = next(
                                g["demo_version"]
                                for g in self.store.artifacts(s["id"], "graph")
                                if g["context_id"] == evidence_context
                            )
                        evidence.update(
                            context_id=evidence_context,
                            basis=(
                                result.get("base_basis")
                                if evidence_context != graph["context_id"]
                                else graph["basis"]
                            ),
                            scenario_version=evidence_version,
                            citation=citation,
                        )
                        seen[key] = self.store.artifact(s["id"], "evidence", evidence)

                def attach(value):
                    if isinstance(value, dict):
                        if {
                            "source_id",
                            "start_line",
                            "end_line",
                            "quote",
                        } <= value.keys():
                            value["evidence_id"] = seen[
                                canonical(
                                    {
                                        k: value[k]
                                        for k in (
                                            "source_id",
                                            "start_line",
                                            "end_line",
                                            "quote",
                                        )
                                    }
                                )
                            ]
                        else:
                            for child in value.values():
                                attach(child)
                    elif isinstance(value, list):
                        for child in value:
                            attach(child)

                attach(graph)
                attach(result)
                if self.hook:
                    self.hook("before_publish", j)
                if cancelled():
                    raise DemoError("cancelled")
                self.store.finish(
                    j,
                    "PARTIAL" if graph["coverage"] == "PARTIAL" else "SUCCEEDED",
                    graph=graph,
                    result=result,
                    manifest=manifest,
                )
            except Exception as exc:
                # If restoration itself fails, leave RUNNING+reservation intact for safe startup recovery.
                latest = self.store.session(s["id"])
                if (
                    latest["revision"] == j["session_revision"]
                    and latest["pending_job_id"] == j["id"]
                ):
                    self.snapshots.materialize(s["id"], latest["scenario_version"])
                    code = exc.code if isinstance(exc, DemoError) else "worker_failed"
                    self.store.finish(
                        j, "CANCELLED" if code == "cancelled" else "FAILED", error=code
                    )
            return True

    def run(self):
        with locked(self.store.root / "worker.lock", nonblocking=True):
            self.recover()
            while not self.stop.is_set():
                if not self.run_once():
                    self.stop.wait(0.15)
