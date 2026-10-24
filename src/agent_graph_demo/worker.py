"""One installation worker; recovery restores files before releasing reservations."""

import threading
import time

from agent_graph.output_contracts import ContractError, check_core_codes

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
                for document in (graph, result):
                    try:
                        check_core_codes(document)
                    except ContractError:
                        # An unknown core code is incompatible output, never a green job.
                        raise DemoError("incompatible_core_output") from None
                graph["demo_version"] = manifest["scenario_version"]
                seen = {}
                from .contracts import canonical

                # A proposal keeps citations from the context it was made on, which may be
                # neither this graph's context nor the analysis base (e.g. a B correction seen at E).
                origins = {}
                for proposal in graph.get("proposals", []):
                    for c in proposal["proposal"]["citations"]:
                        origins.setdefault(
                            canonical(c), (proposal["context_id"], proposal["basis"])
                        )
                pending = {}
                for citation in citations([graph, result]):
                    key = canonical(citation)
                    if key in pending:
                        continue
                    candidates = [(graph["context_id"], graph["basis"])]
                    if key in origins:
                        candidates.append(origins[key])
                    if p.get("base_context_id"):
                        candidates.append((p["base_context_id"], result.get("base_basis")))
                    pending[key] = (citation, candidates)
                # One core process validates every citation of the job (no per-citation fan-out).
                checked = call("evidence_batch", message=dict(items=[
                    dict(contexts=[c for c, _ in candidates], citation=citation)
                    for citation, candidates in pending.values()]))["results"] if pending else []
                if len(checked) != len(pending):
                    raise DemoError("cli_invalid_json")
                for (key, (citation, candidates)), outcome in zip(pending.items(), checked):
                    if not isinstance(outcome, dict) or "evidence" not in outcome:
                        code = outcome.get("error") if isinstance(outcome, dict) else None
                        raise DemoError(code if isinstance(code, str) and code.replace("_", "").isalnum()
                                        else "cli_invalid_json")
                    evidence_context = outcome["context_id"]
                    basis = dict(candidates)[evidence_context]
                    evidence = outcome["evidence"]
                    evidence_version = manifest["scenario_version"]
                    if evidence_context != graph["context_id"]:
                        evidence_version = next(
                            g["demo_version"]
                            for g in self.store.artifacts(s["id"], "graph")
                            if g["context_id"] == evidence_context
                        )
                    evidence.update(
                        context_id=evidence_context,
                        basis=basis,
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
