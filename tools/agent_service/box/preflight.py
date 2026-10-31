"""No-publication recovery reconciliation, using the selected release's code.

The legacy adapter is only reached behind guard's exact release14e manifest
allowlist. No PROFILE replacement, cross-version imports or HTTP writes.
"""

from __future__ import annotations

import sys
import json
import subprocess
from pathlib import Path
import uuid


class PreflightError(Exception):
    def __init__(self, code):
        self.code = code


def legacy_reopen(store, providers, event):
    """Explicit queue-schema-1 adapter for release14e, which predates basis reopen."""
    now = store.clock()
    with store._tx() as db:
        for row in db.execute("SELECT r.* FROM resources r WHERE r.closed=0 AND r.version IS NOT NULL "
                              "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.resource_id=r.resource_id "
                              "AND j.generation=r.generation AND j.state IN ('QUEUED','RUNNING'))").fetchall():
            if row["provider"] not in providers:
                continue
            generation = row["generation"] + 1
            store._revoke(db, row["resource_id"], generation, "box_recovery")
            db.execute("UPDATE resources SET generation=?, updated_at=? WHERE resource_id=?",
                       (generation, now, row["resource_id"]))
            db.execute("INSERT INTO jobs(job_id,resource_id,generation,resource_version,event_id,state,"
                       "not_before,deadline,created_at,updated_at) VALUES(?,?,?,?,?,'QUEUED',?,?,?,?)",
                       (uuid.uuid4().hex, row["resource_id"], generation, row["version"], event, now,
                        now + store.limits.job_deadline_seconds, now, now))
            store._history(db, row["resource_id"], "generation_opened", generation=generation,
                           event_id=event, reason="box_recovery")


def main():
    target, config, digest, backup = sys.argv[1:]
    root = Path(target)
    sys.path[:0] = [str(root / "app/src"), str(root / "app")]
    from argparse import Namespace
    from agent_service.__main__ import _service

    service, _ = _service(Namespace(config=config, analyzer=None))
    cfg = json.loads(Path(config).read_text(encoding="utf-8"))
    policy = json.loads(Path(cfg["core"]["policy_path"]).read_text(encoding="utf-8"))
    for repository in policy["repositories"]:
        if not Path(repository["root"]).is_dir():
            raise PreflightError("recovery_source_missing")
        subprocess.run(["git", "-C", repository["root"], "cat-file", "-e",
                        repository["revision"] + "^{commit}"], check=True, capture_output=True)
    # Full listings, not a restored timestamp's bounded window; fetch every known
    # resource too. Do not permit a failed provider to be hidden by reconcile().
    snapshots = []
    for provider, connector in service.connectors.items():
        if provider == "github":
            connector.pin_revisions(None)
        ids = {rid for rid, _ in connector.reconcile_candidates(None)}
        ids.update(r["resource_id"] for r in service.store.resources(provider))
        snapshots.extend(connector.fetch(rid) for rid in sorted(ids))
    service.recover()
    service.reconcile()
    sources = service.analyzer.query().source_freshness()
    if not sources or any(s.get("status") == "UNAVAILABLE" for s in sources):
        raise PreflightError("recovery_source_unavailable")
    for snapshot in snapshots:
        service._apply(snapshot, "box_recovery_snapshot")
    token = f"{digest}:{backup}"
    if service.store.checkpoint("box_recovery") != token:
        reopen = getattr(service.store, "reopen_open_resources", None)
        if reopen:
            reopen(reason="box_recovery", event_id="box_recovery", providers=set(service.connectors))
        else:
            legacy_reopen(service.store, set(service.connectors), "box_recovery")
        service.store.checkpoint("box_recovery", token)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        # Connector reason codes are safe; arbitrary exception messages are not.
        print(json.dumps({"ok": False, "code": code}))
        raise SystemExit(1)
