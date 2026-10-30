"""Author-owned executable fixture. Expectations never enter the analysis policy.

Only the explicit operator requirement and service addresses are configuration.
The analyzer reads Git objects; this harness alone executes trusted fixture files.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types
from unittest.mock import patch

from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "m4_a"


class Fixture:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.repositories = self.root / "repositories"
        shutil.copytree(FIXTURES, self.repositories)
        self.pins = {}
        for repo in ("depot", "dispatch", "wrapped", "ledger"):
            self.git(repo, "init", "-q", "--initial-branch=main")
            self.pins[repo] = self.commit(repo, "base")
        self.store = Store(self.root / "state")
        self.policy = self.make_policy()
        self.graph = Graph(self.policy, self.store)

    def close(self):
        self.store.close()

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-c", "user.name=M4 author fixture", "-c",
            "user.email=m4-author@example.invalid", "-c", "core.hooksPath=/dev/null", "-c",
            "commit.gpgsign=false", "-C", str(self.repositories / repo), *args], text=True,
            env={**{k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR"}},
                 "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_AUTHOR_DATE": "2026-10-28T00:00:00Z",
                 "GIT_COMMITTER_DATE": "2026-10-28T00:00:00Z"}).strip()

    def commit(self, repo, message):
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-q", "-m", message)
        return self.git(repo, "rev-parse", "HEAD")

    def make_policy(self, exclude=(), *, requirements=True):
        rule = self.repositories / "dispatch/requirement.md"
        return Policy.model_validate(dict(installation_id="m4-a-author", environment="test", subject="author",
            capabilities=["read_context", "maintain", "propose", "report_check", "correct"],
            repositories=[dict(id=r, service=r, root=str(self.repositories / r), snapshot="git", revision=sha)
                          for r, sha in sorted(self.pins.items()) if r not in exclude],
            addresses=[dict(service="depot", base_url="https://edge.example.test/v2"),
                       dict(service="ledger", base_url="https://ledger.example.test")],
            requirements=[dict(id="R-dispatch-all", repository="dispatch", path="requirement.md",
                sha256=hashlib.sha256(rule.read_bytes()).hexdigest(), issuer="M4-A author test operator",
                service="depot", path_template="/parcels", consumer="dispatch", predicate="complete_collection")]
                if requirements and "dispatch" not in exclude else []))

    def context(self, graph=None, exclude=()):
        return (graph or self.graph).prepare_context(revisions={k: v for k, v in self.pins.items() if k not in exclude})

    def change(self, repo, relative, text, message):
        (self.repositories / repo / relative).write_text(text)
        self.pins[repo] = self.commit(repo, message)

    def analyze(self, base):
        return self.graph.analyze_change(base["id"], revisions=self.pins)

    @contextmanager
    def runtime(self):
        """Execute actual FastAPI handlers over in-process ASGI, with a requests.get shim.

        The shim delegates URL/query to a mounted ASGI application; it supplies no
        expected result or consumer map. No real requests package/network is claimed.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        namespaces = {}
        for name in ("depot", "ledger"):
            namespace = {"__name__": "m4_a_" + name}
            path = self.repositories / name / "api.py"
            exec(compile(path.read_text(), str(path), "exec"), namespace)
            namespaces[name] = namespace
        gateway = FastAPI()
        gateway.mount("/v2", namespaces["depot"]["app"])
        requests = types.ModuleType("requests")
        calls = []
        with TestClient(gateway, base_url="https://edge.example.test") as client:
            def get(url, **kwargs):
                calls.append({"url": url, "query": kwargs.get("params", {})})
                return client.get(url, **kwargs)
            requests.get = get
            with patch.dict(sys.modules, {"requests": requests}):
                consumers = {}
                for name in ("dispatch", "wrapped"):
                    path = self.repositories / name / "client.py"
                    namespace = {"__name__": "m4_a_" + name}
                    exec(compile(path.read_text(), str(path), "exec"), namespace)
                    consumers[name] = namespace["export"]
                yield consumers, calls
