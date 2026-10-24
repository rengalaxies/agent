import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from tools.autonomous_mvp import fixtures, generate_cases, oracle_check, program as program_mod

BASE, PROGRAM, CASES = program_mod.load()
ORACLE = program_mod.load_oracle(BASE)
SECTION_8 = {"F01_true_consumer", "F02_same_name_operation", "F03_false_hint", "F04_unsupported_wrapper",
             "F05_source_unavailable", "F06_forged_refs", "F07_prompt_injection", "F08_justified_unknown",
             "F09_step_limit", "F10_timeout", "F11_config_context", "F12_intent_link",
             "F13_requirement_at_risk", "F14_paginating_consumer"}


def split(name):
    return [c for c in CASES.values() if c["split"] == name]


def consumer_names(cases):
    return {r["id"] for c in cases for r in c["repositories"]} - {"orders", "notifier"}


class CorpusShape(unittest.TestCase):
    def test_committed_corpus_equals_generator_output(self):
        for relative, text in generate_cases.outputs().items():
            self.assertEqual((BASE / relative).read_bytes().replace(b"\r\n", b"\n"), text.encode(), relative)

    def test_committed_manifest_is_current(self):
        stored = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["manifest_digest"], program_mod.manifest()["manifest_digest"])

    def test_every_section_8_family_is_in_both_splits(self):
        self.assertEqual({c["family"] for c in split("development")}, SECTION_8)
        self.assertEqual({c["family"] for c in split("evaluation")}, SECTION_8)
        self.assertEqual((len(split("development")), len(split("evaluation"))), (20, 40))

    def test_development_and_evaluation_share_no_names_tasks_or_snapshots(self):
        dev, ev = split("development"), split("evaluation")
        self.assertFalse(consumer_names(dev) & consumer_names(ev))
        self.assertFalse({c["task"]["key"] for c in dev} & {c["task"]["key"] for c in ev})
        snapshots = lambda cases: {fixtures.commit_sha(r["files"]) for c in cases for r in c["repositories"]
                                   if r["id"] not in ("orders", "notifier")}
        self.assertFalse(snapshots(dev) & snapshots(ev))

    def test_every_expected_claim_has_a_confidence_band_and_every_case_an_outcome(self):
        for case_id, o in ORACLE.items():
            self.assertTrue(o["acceptable_outcomes"], case_id)
            from agent_graph.constitution import OUTCOMES
            self.assertLessEqual(set(o["acceptable_outcomes"]), set(OUTCOMES), case_id)
            self.assertTrue(o["rationale"], case_id)
            for c in o["required_claims"] + o["forbidden_claims"] + o["allowed_claims"] + o["unverifiable_claims"]:
                order = ("CANDIDATE", "CONFIRMED_WITHIN_PROFILE")
                self.assertLessEqual(order.index(c["min_confidence"]), order.index(c["max_confidence"]), case_id)

    def test_beyond_static_group_requires_candidates_not_facts(self):
        beyond = [k for k, o in ORACLE.items() if o["beyond_static"] and CASES[k]["split"] == "evaluation"]
        self.assertEqual(len(beyond), 9)
        for k in beyond:
            self.assertTrue(any(c["max_confidence"] == "CANDIDATE" for c in ORACLE[k]["required_claims"]), k)

    def test_case_files_carry_no_expected_answer(self):
        forbidden = ("required_claims", "forbidden_claims", "impact", "rationale", "entrypoints", "oracle")
        for path in sorted((BASE / "cases").glob("*/*.json")):
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                self.assertNotIn(f'"{word}"', text, path.name)


class OracleGrounding(unittest.TestCase):
    """The oracle is checked by executing fixtures, so it can be wrong and this must notice."""

    SAMPLE = ("D03", "D07", "D09", "D16", "D18", "D19", "D20", "E03b", "E04b", "E05a", "E07a", "E11c", "E13b", "E14a")

    def check(self, case_id, oracle):
        with tempfile.TemporaryDirectory() as work:
            return oracle_check.check_case(CASES[case_id], oracle, work)

    def test_oracle_matches_executed_fixtures_for_one_case_of_every_kind(self):
        for case_id in self.SAMPLE:
            self.assertEqual(self.check(case_id, ORACLE[case_id]), [], case_id)

    def test_a_decoy_marked_as_required_is_caught(self):
        o = copy.deepcopy(ORACLE["D03"])
        o["required_claims"].append(o["forbidden_claims"][0])
        self.assertTrue(any(p.startswith("claim_not_observed") for p in self.check("D03", o)))

    def test_impact_contradicting_the_requirement_test_is_caught(self):
        o = copy.deepcopy(ORACLE["D19"])
        o["impact"] = {k: "NOT_AT_RISK" for k in o["impact"]}
        self.assertIn("impact_not_grounded:vat-export", self.check("D19", o))

    def test_paginating_consumer_cannot_be_declared_at_risk(self):
        o = copy.deepcopy(ORACLE["D20"])
        o["impact"] = {k: "AT_RISK" for k in o["impact"]}
        self.assertTrue(self.check("D20", o))


class StaticProfileAgreement(unittest.TestCase):
    """Static edges must be inside the extractor's grammar and beyond-static claims outside it."""

    def test_extractor_finds_exactly_the_static_edges(self):
        from agent_graph.contracts import Policy
        from agent_graph.discovery import extract
        from agent_graph.sources import collect
        for case_id, case in sorted(CASES.items()):
            with tempfile.TemporaryDirectory() as work:
                repos = fixtures.materialize(case, Path(work))
                policy = Policy.model_validate(dict(
                    installation_id="amvp-2b", environment="synthetic-fixture", subject="test",
                    capabilities=["read_context"], addresses=case["addresses"],
                    repositories=[dict(id=r["id"], service=r["service"], root=repos[r["id"]]["root"],
                                       revision=repos[r["id"]]["commit"]) for r in case["repositories"]]))
                collected = collect(policy)
                graph = extract(policy, collected)
            # Every fixture file must reach the model; only the deliberately unavailable repo is a gap.
            hidden = [g for g in collected["gaps"] if g["code"] != "source_unavailable"]
            self.assertEqual(hidden, [], case_id)
            readable = sum(len(r["files"]) for r in case["repositories"] if r["availability"] == "available")
            self.assertEqual(len(collected["sources"]), readable, case_id)
            ops = {o["id"]: o for o in graph["operations"]}
            found = {(d["repository"], d["consumer"], ops[d["operation_id"]]["service"],
                      ops[d["operation_id"]]["method"], ops[d["operation_id"]]["path"]) for d in graph["dependencies"]}
            key = lambda c: (c["consumer_repository"], c["consumer_service"], c["provider_service"], c["method"],
                             c["path_template"])
            for c in ORACLE[case_id]["static_edges"]:
                self.assertIn(key(c), found, case_id)
            for c in ORACLE[case_id]["required_claims"]:
                if c["max_confidence"] == "CANDIDATE":
                    self.assertNotIn(key(c), found, case_id)
            for c in ORACLE[case_id]["forbidden_claims"]:
                self.assertNotIn(key(c), found, case_id)


class Fixtures(unittest.TestCase):
    def test_commit_identity_is_computed_from_bytes_and_matches_git(self):
        with tempfile.TemporaryDirectory() as work:
            repos = fixtures.materialize(CASES["E05a"], Path(work))
        for r in CASES["E05a"]["repositories"]:
            self.assertEqual(repos[r["id"]]["commit"], fixtures.commit_sha(r["files"]))
            self.assertEqual(repos[r["id"]]["available"], r["availability"] == "available")

    def test_unavailable_repository_is_absent_on_disk(self):
        with tempfile.TemporaryDirectory() as work:
            repos = fixtures.materialize(CASES["E05a"], Path(work))
            hidden = [r for r in CASES["E05a"]["repositories"] if r["availability"] != "available"][0]
            self.assertFalse(os.path.exists(repos[hidden["id"]]["root"]))

    def test_one_changed_byte_changes_the_commit(self):
        files = dict(CASES["D01"]["repositories"][1]["files"])
        before = fixtures.commit_sha(files)
        path = sorted(files)[0]
        files[path] += " "
        self.assertNotEqual(before, fixtures.commit_sha(files))

    def test_paths_escaping_the_repository_are_rejected(self):
        for bad in ("../x.py", "a/../../x.py", ".git/config", "/etc/x", "a\\b.py"):
            with self.assertRaises(fixtures.FixtureError):
                fixtures.tree_sha({bad: "x"})


if __name__ == "__main__":
    unittest.main()
