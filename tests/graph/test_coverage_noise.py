from pathlib import Path
import tempfile
import unittest

from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store

PROVIDER = '''from fastapi import FastAPI

app = FastAPI()


@app.get("/orders")
def list_orders(day: str, page_size: int | None = 100):
    return {"items": store.read(day, page_size)}
'''
NOT_HTTP = '''import os


def settings(raw):
    region = os.environ.get("REGION", "eu")
    cached = CACHE.get(raw)
    return raw.get("day"), region, cached
'''
UNSUPPORTED = '''import httpx
import requests

BASE_URL = "https://orders.test"
session = requests.Session()


class Gateway:
    def load(self):
        return self.client.get("/orders")


def load(day):
    first = httpx.get(BASE_URL + "/orders", params={"day": day})
    second = session.get(BASE_URL + "/orders")
    return first, second


def stream(target):
    with httpx.Client() as http:
        return http.post(target)
'''
SUPPORTED = '''import requests


def load(day):
    return requests.get("https://orders.test/orders", params={"day": day}).json()
'''


class CoverageNoiseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        files = {"orders": {"api.py": PROVIDER}, "tools": {"config.py": NOT_HTTP},
                 "gateway": {"client.py": UNSUPPORTED}, "reporting": {"client.py": SUPPORTED}}
        for repo, content in files.items():
            for name, text in content.items():
                (root / repo).mkdir(parents=True, exist_ok=True)
                (root / repo / name).write_text(text)
        self.policy = Policy.model_validate(dict(
            installation_id="acme", environment="test", subject="t", capabilities=["read_context", "maintain"],
            repositories=[dict(id=r, service=r, root=str(root / r), revision="w") for r in files],
            addresses=[dict(service="orders", base_url="https://orders.test")]))
        self.store = Store(root / "state")
        self.context = Graph(self.policy, self.store).prepare_context()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def gaps(self, repository):
        sources = {s["id"]: s for s in self.context["sources"].values()}
        return [g for g in self.context["graph"]["gaps"]
                if sources.get(g.get("evidence", {}).get("source_id"), {}).get("repository") == repository]

    def status(self, repository):
        return {f["repository"]: f["status"] for f in self.context["graph"]["file_coverage"]}[repository]

    def test_route_decorators_and_mapping_lookups_are_not_unsupported_clients(self):
        self.assertEqual(self.gaps("orders"), [])
        self.assertEqual(self.gaps("tools"), [])
        self.assertEqual(self.status("orders"), "EXTRACTED")
        self.assertEqual(self.status("tools"), "NO_DEPENDENCY_SIGNALS")

    def test_real_unsupported_http_calls_stay_visible(self):
        lines = sorted(g["evidence"]["start_line"] for g in self.gaps("gateway"))
        self.assertEqual(lines, [10, 14, 15, 21])
        self.assertTrue(all(g["code"] == "unknown_http_client" for g in self.gaps("gateway")))
        self.assertEqual(self.status("gateway"), "UNSUPPORTED_CALLS")
        self.assertEqual(self.context["coverage"], "PARTIAL")

    def test_supported_call_is_extracted_and_counted(self):
        self.assertEqual(self.status("reporting"), "EXTRACTED")
        self.assertEqual({d["consumer"] for d in self.context["graph"]["dependencies"]}, {"reporting"})


if __name__ == "__main__":
    unittest.main()
