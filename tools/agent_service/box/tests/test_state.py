"""Backups and the rollback decision: the state is restored only from a verified copy of a compatible schema."""

import errno
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.agent_service.box import state as box_state
from tools.agent_service.box.layout import Layout

ROOT = Path(__file__).resolve().parents[4]

RELEASE_V1 = {"service_store": {"version": 1, "opens": "equal"}, "graph_store": {"version": 2, "opens": "older_or_equal"}}


def make_state(state: Path, *, service_schema=1, graph_schema=2, events=3):
    (state / "service").mkdir(parents=True)
    (state / "core").mkdir(parents=True)
    c = sqlite3.connect(state / "service" / "service.sqlite")
    c.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE events(id INTEGER); CREATE TABLE resources(comment_id TEXT); CREATE TABLE jobs(id INTEGER);
        CREATE TABLE intents(id INTEGER); CREATE TABLE history(id INTEGER);
    """)
    c.execute("INSERT INTO meta VALUES('schema_version', ?)", (str(service_schema),))
    c.executemany("INSERT INTO events VALUES(?)", [(i,) for i in range(events)])
    c.execute("INSERT INTO resources VALUES('comment-1')")
    c.commit()
    c.close()
    g = sqlite3.connect(state / "core" / "graph.sqlite3")
    g.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT); CREATE TABLE artifacts(id TEXT);"
                    "CREATE TABLE proposals(id TEXT);")
    g.execute("INSERT INTO meta VALUES('store_schema', ?)", (str(graph_schema),))
    g.commit()
    g.close()


def add_event(state: Path):
    c = sqlite3.connect(state / "service" / "service.sqlite")
    c.execute("INSERT INTO events VALUES(99)")
    c.commit()
    c.close()


class Compatibility(unittest.TestCase):
    def test_service_store_must_match_exactly(self):
        ok, why = box_state.compatible(RELEASE_V1, {"service_store": 2, "graph_store": 2})
        self.assertFalse(ok)
        self.assertIn("service_store 2", why[0])

    def test_graph_store_may_be_older_but_not_newer(self):
        self.assertTrue(box_state.compatible(RELEASE_V1, {"service_store": 1, "graph_store": 1})[0])
        self.assertFalse(box_state.compatible(RELEASE_V1, {"service_store": 1, "graph_store": 3})[0])

    def test_fresh_state_is_compatible_with_any_release(self):
        self.assertTrue(box_state.compatible(RELEASE_V1, {"service_store": None, "graph_store": None})[0])


class Backups(unittest.TestCase):
    def setUp(self):
        self.prefix = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.prefix, True)
        self.layout = Layout.at(self.prefix)
        make_state(self.layout.state)

    def test_schemas_are_read_from_the_files(self):
        self.assertEqual(box_state.schemas(self.layout.state), {"service_store": 1, "graph_store": 2})

    def test_restore_brings_back_exactly_the_backed_up_rows(self):
        meta = box_state.create(self.layout, label="pre-update", release={"name": "r1"})
        add_event(self.layout.state)
        self.assertEqual(box_state.counts(self.layout.state)["events"], 4)
        box_state.restore(self.layout, meta["name"])
        self.assertEqual(box_state.counts(self.layout.state)["events"], 3)
        self.assertEqual(box_state.counts(self.layout.state)["delivered_comments"], 1)

    def test_modified_backup_is_refused_and_state_is_untouched(self):
        meta = box_state.create(self.layout, label="manual", release=None)
        copy = self.layout.backups / meta["name"] / "state" / "service" / "service.sqlite"
        c = sqlite3.connect(copy)
        c.execute("INSERT INTO events VALUES(7)")
        c.commit()
        c.close()
        add_event(self.layout.state)
        with self.assertRaises(box_state.BackupError) as ctx:
            box_state.restore(self.layout, meta["name"])
        self.assertEqual(ctx.exception.code, "backup_file_modified")
        self.assertEqual(box_state.counts(self.layout.state)["events"], 4)

    def test_unknown_backup_name_is_refused_without_touching_paths(self):
        with self.assertRaises(box_state.BackupError) as ctx:
            box_state.verify(self.layout, "../../etc")
        self.assertEqual(ctx.exception.code, "backup_not_found")

    def leftovers(self) -> list[str]:
        """Restore working files that must not outlive a restore, successful or not."""
        return sorted(str(p.relative_to(self.layout.state)) for p in self.layout.state.rglob(".*")
                      if p.is_file())

    def test_disk_full_while_copying_the_backup_keeps_the_current_queue(self):
        # Review of PR #60: restore deleted service.sqlite before the copy succeeded; ENOSPC left no queue.
        meta = box_state.create(self.layout, label="manual", release=None)
        add_event(self.layout.state)

        def full_disk(src, dst):
            Path(dst).write_bytes(Path(src).read_bytes()[:100])
            raise OSError(errno.ENOSPC, "No space left on device")

        with mock.patch.object(box_state.shutil, "copyfile", full_disk), self.assertRaises(OSError):
            box_state.restore(self.layout, meta["name"])
        self.assertEqual(box_state.counts(self.layout.state)["events"], 4)
        self.assertFalse(box_state.restore_unfinished(self.layout.state))
        self.assertEqual(self.leftovers(), [])

    def test_permission_error_while_swapping_returns_the_previous_databases(self):
        meta = box_state.create(self.layout, label="manual", release=None)
        add_event(self.layout.state)
        real = os.replace

        def refuse_graph(src, dst):
            if str(src).endswith(".graph.sqlite3.restore"):
                raise PermissionError(errno.EACCES, "Permission denied")
            return real(src, dst)

        with mock.patch.object(box_state.os, "replace", refuse_graph), self.assertRaises(PermissionError):
            box_state.restore(self.layout, meta["name"])
        counts = box_state.counts(self.layout.state)
        self.assertEqual((counts["events"], counts["graph_artifacts"]), (4, 0))
        self.assertFalse(box_state.restore_unfinished(self.layout.state))
        self.assertEqual(self.leftovers(), [])

    def kill_restore_at(self, point: str, name: str):
        code = (f"import os, sys; sys.path[:0] = {[str(ROOT / 'src'), str(ROOT)]!r}\n"
                "from tools.agent_service.box import state\nfrom tools.agent_service.box.layout import Layout\n"
                f"state.restore(Layout.at({str(self.prefix)!r}), {name!r}, "
                f"fault=lambda p: os._exit(137) if p == {point!r} else None)\n")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(done.returncode, 137, done.stderr)

    def test_restore_killed_after_moving_the_databases_aside_is_returned_by_recover(self):
        meta = box_state.create(self.layout, label="manual", release=None)
        add_event(self.layout.state)
        self.kill_restore_at("aside", meta["name"])
        self.assertFalse((self.layout.state / box_state.DATABASES["service"]).exists())
        self.assertTrue(box_state.restore_unfinished(self.layout.state))  # launch.py refuses to start on this
        self.assertEqual(box_state.recover(self.layout)["outcome"], "returned_previous_state")
        self.assertEqual(box_state.counts(self.layout.state)["events"], 4)
        self.assertEqual(self.leftovers(), [])

    def test_restore_killed_before_the_count_check_is_returned_by_recover(self):
        meta = box_state.create(self.layout, label="manual", release=None)
        add_event(self.layout.state)
        self.kill_restore_at("swapped", meta["name"])
        self.assertEqual(box_state.recover(self.layout)["outcome"], "returned_previous_state")
        self.assertEqual(box_state.counts(self.layout.state)["events"], 4)
        box_state.restore(self.layout, meta["name"])  # and the same restore then goes through
        self.assertEqual(box_state.counts(self.layout.state)["events"], 3)
        self.assertEqual(self.leftovers(), [])

    def test_backup_that_fails_half_way_leaves_no_partial_copy(self):
        with mock.patch.object(box_state, "_integrity", return_value=False), self.assertRaises(box_state.BackupError):
            box_state.create(self.layout, label="manual", release=None)
        self.assertEqual(list(self.layout.backups.iterdir()), [])

    def test_prune_keeps_the_rollback_point(self):
        names = [box_state.create(self.layout, label=f"b{i}", release=None)["name"] for i in range(4)]
        removed = box_state.prune(self.layout, keep=2, protect={names[0]})
        self.assertEqual(removed, [names[1]])
        left = [m["name"] for m in box_state.listing(self.layout)]
        self.assertEqual(left, [names[0], names[2], names[3]])


if __name__ == "__main__":
    unittest.main()
