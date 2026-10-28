"""Readiness corpus and oracle of the current revision: reproducible, disjoint, grounded by execution.

6-r1 and 6-r2 are historical: their files must stay byte-equal to what their manifests pinned.
"""
import copy
import json
import unittest

from tools.autonomous_mvp.readiness import generate, oracle as oracle_mod, program, world
from tools.autonomous_mvp.scorer import rate

BASE, PROGRAM, CHANGES = program.load()
ORACLE = {**program.load_oracle("development"), **program.load_oracle("heldout")}


def split(name):
    return [c for c in CHANGES.values() if c["split"] == name]


def facts(change_id):
    return ORACLE[change_id]["world"]


class CorpusShape(unittest.TestCase):
    def test_committed_corpus_equals_generator_output(self):
        for relative, text in generate.outputs().items():
            self.assertEqual((BASE / relative).read_bytes().replace(b"\r\n", b"\n"), text.encode("utf-8"), relative)

    def test_closed_6r3_manifest_program_and_ledgers_remain_intact(self):
        # 6-r3's held-out result belongs to its original code. Post-run fixes
        # must not rewrite the manifest beneath that result.
        report = program.historical('6-r3')
        self.assertTrue(report['intact'], report['problems'])
        self.assertTrue(report['manifest_digest'].startswith('e1c04f17'))

    def test_closed_6r3_is_not_current_after_publication_fixes(self):
        current, _ = program.status()
        self.assertFalse(current)
        # Both readiness CLI and held-out runner require this same status()
        # gate; preserve its refusal rather than refreshing the frozen evidence.
        import subprocess
        import sys
        check = subprocess.run([sys.executable, '-m', 'tools.autonomous_mvp.readiness.program', '--check'],
                               capture_output=True, text=True)
        self.assertNotEqual(check.returncode, 0)
        self.assertIn('MANIFEST_STALE', check.stderr)

    def test_sizes_and_every_family_in_both_splits(self):
        self.assertEqual((len(split("development")), len(split("heldout"))), (22, 70))
        for name in world.SPLITS:
            self.assertEqual({c["family"] for c in split(name)}, set(world.FAMILIES), name)
        per_family = {f: sum(c["family"] == f for c in split("heldout")) for f in world.FAMILIES}
        self.assertEqual(set(per_family.values()), {5})

    def test_splits_share_no_service_names_task_keys_or_file_bytes(self):
        def names(cases):
            return {n for c in cases for n in c["repositories"]}

        def blobs(cases):
            return {text for c in cases for r in c["repositories"].values() for b in r["branches"].values()
                    for text in b["files"].values()}

        dev, held = split("development"), split("heldout")
        self.assertFalse(names(dev) & names(held))
        self.assertFalse({c["jira"]["key"] for c in dev} & {c["jira"]["key"] for c in held})
        self.assertFalse({c["jira"]["project"] for c in dev} & {c["jira"]["project"] for c in held})
        self.assertFalse(blobs(dev) & blobs(held))

    def test_change_files_carry_no_expected_answer_or_world_fact(self):
        forbidden = ("severity", "expected", "acceptable", "deployment_env", "items_on_fixture_day", "negatives",
                     "oracle", "consumer_kinds", "_URL\": \"https")
        for path in sorted((BASE / "changes").glob("*/*.json")):
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                self.assertNotIn(word, text, path.name)

    def test_sample_size_numbers_in_program_are_the_wilson_half_widths(self):
        stated = PROGRAM["sample_size"]["wilson95_half_width_at_n70"]
        for key, value in stated.items():
            p = float(key[1:])
            low, high = rate(round(p * 70), 70)["wilson95"]
            self.assertAlmostEqual(value, (high - low) / 2, delta=0.0031, msg=key)
        self.assertAlmostEqual(PROGRAM["sample_size"]["zero_event_upper95"]["n70"], rate(0, 70)["wilson95"][1],
                               delta=0.0011)


class OracleGrounding(unittest.TestCase):
    """The oracle is re-derived by executing fixtures, so a wrong oracle must be noticed."""

    def test_every_stored_oracle_matches_a_fresh_execution(self):
        for cid, change in sorted(CHANGES.items()):
            self.assertEqual(oracle_mod.check(change, facts(cid), ORACLE[cid]), [], cid)

    def test_a_flipped_severity_is_caught(self):
        o = copy.deepcopy(ORACLE["D01"])
        name = next(n for n, s in o["pr"]["expected_consumers"].items() if s == "breaking")
        o["pr"]["expected_consumers"][name] = "recheck"
        self.assertIn("pr_not_grounded", oracle_mod.check(CHANGES["D01"], facts("D01"), o))

    def test_a_decoy_caller_declared_affected_is_caught(self):
        o = copy.deepcopy(ORACLE["D01"])
        decoy = next(n for n, s in o["services"].items() if s.get("kind") == "decoy")
        o["pr"]["expected_consumers"][decoy] = "breaking"
        self.assertIn("pr_not_grounded", oracle_mod.check(CHANGES["D01"], facts("D01"), o))

    def test_facts_that_disagree_with_the_provider_code_are_caught(self):
        f = copy.deepcopy(facts("D01"))
        route = f["operation"]["route"]
        f["defaults"]["change"][route] = f["defaults"]["main"][route]
        problems = oracle_mod.check(CHANGES["D01"], f, ORACLE["D01"])
        self.assertIn("provider_code_differs_from_facts:change", problems)

    def test_severity_follows_consumer_behaviour(self):
        # Truncation: a single request loses records, a cursor loop does not; removal breaks everyone.
        for cid, o in ORACLE.items():
            for name, s in o["services"].items():
                if s.get("kind") == "cursor" and o["family"] == "F01_truncation":
                    self.assertEqual(s["severity"], "recheck", (cid, name))
                if s.get("kind") == "single" and o["family"] == "F01_truncation":
                    self.assertEqual(s["severity"], "breaking", (cid, name))
                if s.get("kind") in ("single", "cursor", "explicit") and o["family"] == "F02_operation_removed":
                    self.assertEqual(s["severity"], "breaking", (cid, name))
                if s.get("kind") in ("bystander", "decoy"):
                    self.assertEqual(s["severity"], "none", (cid, name))

    def test_runtime_only_consumers_are_found_only_through_deployment_configuration(self):
        for cid, o in ORACLE.items():
            for name, s in o["services"].items():
                if s.get("kind") != "runtime_env":
                    continue
                code = CHANGES[cid]["repositories"][name]["branches"]["main"]["files"]["client.py"]
                self.assertIn("os.environ[", code)
                self.assertNotIn(".test", code, cid)  # no URL in any readable repository
                expected = "stale_runtime" if o["family"] == "F07_stale_runtime" else "runtime"
                self.assertEqual(s["basis"], expected, (cid, name))

    def test_revoked_consumers_are_affected_but_never_expected(self):
        for cid, o in ORACLE.items():
            for name in o["revoked"]:
                self.assertNotEqual(o["services"][name]["severity"], "none", cid)
                self.assertNotIn(name, o["pr"]["expected_consumers"], cid)
                self.assertNotIn(name, o["negatives"], cid)

    def test_outcome_rules(self):
        cases = [("F01_truncation", "explicit", ["a"], ["a"], {"a": "code"}, ("answer", "answer")),
                 ("F10_ambiguous_jira", "ambiguous", [], ["a"], {"a": "code"}, ("abstain", "answer")),
                 ("F03_no_impact_noop", "service_only", [], [], {}, ("no_impact", "no_impact")),
                 ("F05_runtime_only", "explicit", ["a", "b"], ["a", "b"], {"a": "code", "b": "runtime"},
                  ("partial", "partial")),
                 ("F12_unclassified_change", "explicit", ["a"], ["a"], {"a": "code"}, ("answer", "partial")),
                 ("F13_service_contract_unspecified", "candidate", [], ["a"], {"a": "code"}, ("candidate", "answer"))]
        for family, intent, jira, pr, bases, expected in cases:
            self.assertEqual(oracle_mod.expected_outcomes(family, intent, jira, pr, bases), expected, family)


class WorldDeterminism(unittest.TestCase):
    def test_same_index_same_world_and_different_index_different_world(self):
        a, _ = world.build("heldout", 7)
        b, _ = world.build("heldout", 7)
        c, _ = world.build("heldout", 7 + len(world.FAMILIES))  # same family, other draw
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(a["family"], c["family"])
        self.assertNotEqual(json.dumps(a, sort_keys=True), json.dumps(c, sort_keys=True))


class HistoricalRevision(unittest.TestCase):
    """6-r1 and 6-r2 keep their corpora, manifests and ledgers; 6-r3 shares nothing a tuner could have seen."""

    def test_6r1_files_and_ledgers_are_what_its_manifest_pinned(self):
        report = program.historical("6-r1")
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["manifest_digest"],
                         "6140e378686837750109e0ac79b1287287a5775d7c9db21d4573d62e62dc50f7")
        self.assertEqual(len(report["ledgers"]), 3)

    def test_6r2_files_and_ledgers_are_what_its_manifest_pinned(self):
        report = program.historical("6-r2")
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["manifest_digest"],
                         "45f495273ff32ae8532d957706be990fcfeb1558cbdfd31f710f86d8c3a26524")
        self.assertEqual(len(report["ledgers"]), 2)

    def test_6r1_and_6r2_still_regenerate_byte_for_byte(self):
        for revision in ("6-r1", "6-r2"):
            base = program.program_dir(revision)
            for relative, text in generate.outputs(revision).items():
                self.assertEqual((base / relative).read_bytes().replace(b"\r\n", b"\n"), text.encode("utf-8"),
                                 f"{revision} {relative}")

    def test_6r3_shares_no_name_key_or_file_with_any_6r1_or_6r2_change(self):
        old = {}
        for revision in ("6-r1", "6-r2"):
            old.update({f"{revision}:{k}": v for k, v in program.load(program.program_dir(revision))[2].items()})

        def names(cases):
            return {n for c in cases for n in c["repositories"]}

        def blobs(cases):
            return {text for c in cases for r in c["repositories"].values() for b in r["branches"].values()
                    for text in b["files"].values()}

        new = list(CHANGES.values())
        self.assertFalse(names(new) & names(old.values()))
        self.assertFalse({c["jira"]["key"] for c in new} & {c["jira"]["key"] for c in old.values()})
        self.assertFalse(blobs(new) & blobs(old.values()))

    def test_a_tampered_6r1_ledger_breaks_the_historical_check(self):
        import shutil
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "6-r1"
            shutil.copytree(program.program_dir("6-r1"), root)
            path = root / "results" / "heldout-service-no-model.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledger["manifest_digest"] = "0" * 64
            path.write_text(json.dumps(ledger), encoding="utf-8")
            original = program.program_dir
            program.program_dir = lambda revision=None: root
            try:
                self.assertIn("ledger_not_bound_to_manifest:heldout-service-no-model.json",
                              program.historical("6-r1")["problems"])
            finally:
                program.program_dir = original


if __name__ == "__main__":
    unittest.main()
