"""Opt-in local adapter: real Git + HTTP -> queue -> core, publication held."""

import json
import subprocess
import unittest
from unittest.mock import patch

from agent_graph.contracts import GraphError
from agent_service.config import build
from agent_service.core_analyzer import CoreAnalyzer
from agent_service.service import Service
from agent_service.http import ClientError
from agent_graph.output_contracts import parse_document, ContractError
from tests.graph.test_output_contracts import request
from tests.service import test_bitbucket_probe as fixture
from tests.service import test_bitbucket_read as data
from examples.pilot_orders_reporting.prepare import prepare
from examples.pilot_orders_reporting.demo import policy

try:
    from agent_service.connectors.bitbucket_analysis import (
        BitbucketLocalAnalysisConnector,
    )
except ModuleNotFoundError:
    BitbucketLocalAnalysisConnector = None


class RecordingCore(CoreAnalyzer):
    def analyze(self, request, **kwargs):
        self.last_request = request
        return super().analyze(request, **kwargs)


class VersionTest(unittest.TestCase):
    def test_bitbucket_requires_explicit_new_minor(self):
        doc = request()
        doc["pr"]["provider"] = "bitbucket"
        self.assertEqual(parse_document(doc).pr.provider, "bitbucket")
        doc["schema_version"] = "2.1"
        with self.assertRaises(ContractError):
            parse_document(doc)


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ProbeTest()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.assertIsNotNone(
            BitbucketLocalAnalysisConnector, "local worker adapter missing"
        )
        prepared = prepare(self.f.root / "repos")
        self.pins = {
            k: v["commits"]["main"] for k, v in prepared["repositories"].items()
        }
        self.head = prepared["repositories"]["orders"]["commits"]["pilot-page-limit"]
        self.pr = data.pull_request()
        self.pr["source"]["commit"]["hash"] = self.head
        self.pr["destination"]["commit"]["hash"] = self.pins["orders"]
        self.f.document["bitbucket"]["repositories"]["orders"]["repository_id"] = (
            "orders"
        )
        self.f.document["bitbucket"]["repositories"]["reporting"] = {
            "uuid": data.OTHER,
            "repository_id": "reporting",
        }
        other = data.repository()
        other.update(slug="reporting", full_name="pilot/reporting", uuid=data.OTHER)
        self.f.routes["/2.0/repositories/pilot/reporting"] = other
        self.f.routes[data.PINNED + "/refs/branches/main"]["target"]["hash"] = (
            self.pins["orders"]
        )
        self.f.routes[
            "/2.0/repositories/pilot/%7B33333333-3333-3333-3333-333333333333%7D/refs/branches/main"
        ] = {"name": "main", "target": {"hash": self.pins["reporting"]}}
        self.f.routes[data.PINNED + "/pullrequests"] = {"values": [self.pr]}
        self.f.routes[
            "/2.0/repositories/pilot/%7B33333333-3333-3333-3333-333333333333%7D/pullrequests"
        ] = {"values": []}
        self.f.routes[data.PINNED + "/pullrequests/7"] = self.pr
        policy_path = self.f.root / "policy.json"
        policy_path.write_text(json.dumps(policy(self.f.root / "repos", self.pins)))
        self.f.document.update(
            core={"policy_path": str(policy_path), "state_dir": str(self.f.root / "core")},
            state_path=str(self.f.root / "queue.sqlite"),
            dry_run_dir=str(self.f.root / "sink"),
        )
        self.f.document["bitbucket"]["mode"] = "local_analysis"
        self.store, connectors, backends = build(
            self.f.config(), env_secret=self.f.secrets.__getitem__
        )
        self.connector = connectors["bitbucket"]
        self.analyzer = RecordingCore(
            policy(self.f.root / "repos", self.pins),
            self.f.root / "core",
            code_version="test",
        )
        self.addCleanup(self.analyzer.close)
        self.service = Service(
            store=self.store,
            connectors=connectors,
            analyzer=self.analyzer,
            installation_id="agent-pilot",
            environment="test",
            backends=backends,
        )
        self.rid = "bitbucket:11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222#7"

    def run_worker(self):
        self.service.reconcile()
        return self.service.run_until_idle()

    def test_queue_runs_real_core_with_bitbucket_identity_and_holds_publication(self):
        self.run_worker()
        [job] = self.store.jobs(self.rid)
        self.assertEqual(job["state"], "ANALYZED")
        self.assertEqual(job["result"]["trigger_kind"], "pr")
        self.assertTrue(
            any(f["code"] == "POSSIBLE_TRUNCATION" for f in job["result"]["findings"])
        )
        self.assertEqual(self.store.status()["intents"], {"PENDING": 1})
        self.assertEqual(list((self.f.root / "sink" / "bitbucket").glob("*.json")), [])
        self.assertEqual(self.analyzer.last_request["pr"]["provider"], "bitbucket")
        self.assertEqual(
            self.connector.prepare(self.connector.fetch(self.rid)).subject["provider"],
            "bitbucket",
        )
        self.assertEqual(self.run_worker(), [])
        self.assertEqual(len(self.store.jobs(self.rid)), 1)

    def test_new_pr_version_revokes_old_result(self):
        self.run_worker()
        self.pr["title"] = "ORD-12 revised scope"
        self.run_worker()
        self.assertEqual(self.store.resource(self.rid)["generation"], 2)
        self.assertEqual(self.store.jobs(self.rid)[-1]["state"], "ANALYZED")
        self.assertTrue(
            all(i["state"] != "DELIVERED" for i in self.store.intents(self.rid))
        )

    def test_corrected_head_is_fetched_and_replaces_the_warning(self):
        self.run_worker()
        [original] = self.store.jobs(self.rid)
        self.assertIn("POSSIBLE_TRUNCATION", [f["code"] for f in original["result"]["findings"]])

        orders = self.f.root / "repos" / "orders"
        remote = self.f.root / "orders-remote.git"
        subprocess.run(["git", "clone", "--bare", "--quiet", str(orders), str(remote)], check=True)
        head = subprocess.check_output(
            ["git", "-C", str(remote), "-c", "user.name=Pilot", "-c", "user.email=pilot@example.invalid",
             "commit-tree", self.pins["orders"] + "^{tree}", "-p", self.head, "-m", "Restore page size"],
            text=True,
        ).strip()
        subprocess.run(["git", "-C", str(remote), "update-ref", "refs/heads/pilot-page-limit", head], check=True)
        self.pr["source"]["commit"]["hash"] = head

        def refresh(git, repo):
            if repo.slug == "orders":
                subprocess.run(git.argv("fetch", "--quiet", str(remote),
                               "+refs/heads/pilot-page-limit:refs/heads/pilot-page-limit"), env=git.env, check=True)

        self.connector.refresh_mirrors = True
        with patch.object(self.connector, "_refresh_mirror", side_effect=refresh):
            self.run_worker()
            self.assertEqual(self.run_worker(), [])

        old, current = self.store.jobs(self.rid)
        self.assertEqual(current["generation"], old["generation"] + 1)
        self.assertEqual(current["state"], "ANALYZED")
        self.assertEqual(self.analyzer.last_request["pr"]["head_sha"], head)
        self.assertNotIn("POSSIBLE_TRUNCATION", [f["code"] for f in current["result"]["findings"]])
        self.assertFalse(list((self.f.root / "sink").rglob("*.json")))

    def test_stale_snapshot_is_refused_before_analysis(self):
        snap = self.connector.fetch(self.rid)
        self.pr["title"] = "newer version"
        with self.assertRaisesRegex(ClientError, "bitbucket_snapshot_changed"):
            self.connector.prepare(snap)

    def test_missing_git_objects_fail_without_publication(self):
        self.pr["source"]["commit"]["hash"] = "a" * 40
        self.run_worker()
        self.assertEqual(self.store.jobs(self.rid)[0]["state"], "FAILED")
        self.assertFalse(hasattr(self.analyzer, "last_request"))
        self.assertTrue(
            all(i["state"] == "PENDING" for i in self.store.intents(self.rid))
        )

    def test_refresh_failure_refuses_preloaded_head(self):
        self.connector.refresh_mirrors = True
        with patch.object(self.connector, "_refresh_mirror",
                          side_effect=GraphError("bitbucket_git_fetch_failed")) as refresh:
            self.run_worker()
        refresh.assert_called_once()
        [job] = self.store.jobs(self.rid)
        self.assertEqual(job["state"], "FAILED")
        self.assertFalse(hasattr(self.analyzer, "last_request"))
        self.assertFalse(list((self.f.root / "sink").rglob("*.json")))

    def test_missing_secondary_mainline_is_refused(self):
        route = "/2.0/repositories/pilot/%7B33333333-3333-3333-3333-333333333333%7D/refs/branches/main"
        self.f.routes[route]["target"]["hash"] = "b" * 40
        with self.assertRaisesRegex(ClientError, "bitbucket_git_unavailable"):
            self.connector.prepare(self.connector.fetch(self.rid))
