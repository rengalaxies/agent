"""Backups and the rollback decision: the state is restored only from a verified copy of a compatible schema."""

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from tools.agent_service.box import state as box_state
from tools.agent_service.box.layout import Layout

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

    def test_prune_keeps_the_rollback_point(self):
        names = [box_state.create(self.layout, label=f"b{i}", release=None)["name"] for i in range(4)]
        removed = box_state.prune(self.layout, keep=2, protect={names[0]})
        self.assertEqual(removed, [names[1]])
        left = [m["name"] for m in box_state.listing(self.layout)]
        self.assertEqual(left, [names[0], names[2], names[3]])


if __name__ == "__main__":
    unittest.main()
