"""Read a finalized E4 journal from an independent coordinator process."""
from __future__ import annotations

import sys
from pathlib import Path

from datamesh_release_protocol.engine import scenario_snapshot_id
from datamesh_release_protocol.journal import EventJournal
from run_e4 import three_domains


if __name__ == "__main__":
    scenario = three_domains()
    domains = frozenset(item.consumer_domain for item in scenario.obligations)
    with EventJournal(Path(sys.argv[1]), f"E4:{scenario.scenario_id}:V2",
                      scenario_snapshot_id(scenario), domains) as journal:
        print(journal.finalize().value)
