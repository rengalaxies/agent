"""E4 harness: write one valid domain event, then kill coordinator without cleanup."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from datamesh_release_protocol.distributed import make_event
from datamesh_release_protocol.engine import scenario_snapshot_id
from datamesh_release_protocol.journal import EventJournal
from datamesh_release_protocol.loaders import load_baseline_policy
from datamesh_release_protocol.models import ValidationMode
from datamesh_release_protocol.validators import validate
from run_e4 import three_domains


def main() -> None:
    scenario = three_domains()
    domains = frozenset(item.consumer_domain for item in scenario.obligations)
    proposal = f"E4:{scenario.scenario_id}:V2"
    snapshot = scenario_snapshot_id(scenario)
    isolated = scenario.model_copy(update={"obligations": [item for item in scenario.obligations if item.consumer_domain == "fintech"]})
    verdict = validate(isolated, ValidationMode.V2, load_baseline_policy(Path("policies/v1-ind.yaml")))[0]
    with EventJournal(Path(sys.argv[1]), proposal, snapshot, domains) as journal:
        if not journal.append(make_event(proposal, snapshot, verdict)):
            raise RuntimeError("already finalized")
    os._exit(23)


if __name__ == "__main__":
    main()
