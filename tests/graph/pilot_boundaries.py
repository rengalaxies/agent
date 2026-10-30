"""Diagnostics for known PR72 boundaries; do not turn expected defects into passing assertions."""
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store
from agent_service.intent import match_intent

def run():
    ops = [dict(id="wg", service="warehouse", method="GET", path="/shipments"),
           dict(id="wp", service="warehouse", method="POST", path="/shipments"),
           dict(id="rg", service="remote", method="GET", path="/shipments")]
    expectations = [
        ("documentation", ["warehouse: Change README to show POST /shipments and GET /shipments"], []),
        ("negation_mixed", ["warehouse: GET /shipments unchanged; change POST /shipments payload"], ["wp"]),
        ("scope", ["warehouse POST /shipments changes body; GET /shipments changes size"], [])]
    output = []
    def record(name, expected, actual, basis):
        output.append(dict(case=name, expected=expected, actual=actual, basis=basis,
                           status="PASS" if actual == expected else "DEFERRED_72"))
    for name, text, expected in expectations:
        record(name, expected, match_intent(ops, text).operation_ids,
               "Task is documentation / GET explicitly unchanged / GET provider not disambiguated")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repo = root / "repo"
        repo.mkdir()
        (repo / "app.py").write_text('from fastapi import FastAPI\napp=FastAPI()\n@app.get("/shipments")\ndef listing():\n    return []\n')
        def git(*args):
            return subprocess.check_output(["git", "-c", "user.name=Author", "-c", "user.email=author@example.invalid",
                "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args], text=True).strip()
        git("init", "-q")
        git("add", ".")
        git("commit", "-qm", "authored pinned snapshot")
        policy = Policy.model_validate(dict(installation_id="review", environment="test", subject="author",
            capabilities=["read_context", "maintain", "propose"], addresses=[],
            repositories=[dict(id="warehouse", service="warehouse", root=str(repo), snapshot="git",
                               revision=git("rev-parse", "HEAD"))]))
        store = Store(root / "state")
        try:
            graph = Graph(policy, store)
            with patch("agent_graph.engine.PROFILE", "previous-profile"), patch("agent_graph.sources.PROFILE", "previous-profile"):
                old = graph.prepare_context()
                source = next(iter(old["sources"].values()))
                graph.propose(old["id"], dict(key="profile-test", kind="hypothesis", statement="Revalidate after upgrade",
                    citations=[dict(source_id=source["id"], start_line=1, end_line=1, quote="from fastapi import FastAPI")]))
            record("old_pinned_profile", "STALE", graph.freshness(old)["status"],
                   "Extractor identity changed despite identical pinned tree")
            current = graph.prepare_context()
            record("old_knowledge_profile", "STALE", graph.proposals(current)[0]["status"],
                   "Knowledge basis used prior extractor; do not delete history")
            (repo / "app.py").write_text('from fastapi import FastAPI\napp=FastAPI()\nclass Plain:\n    def get(self,path):\n        return lambda f:f\napp=Plain()\n@app.get("/ghost")\ndef ghost():\n    return []\n')
            git("add", ".")
            git("commit", "-qm", "ordinary object, no HTTP route")
            context = graph.prepare_context(revisions={"warehouse": git("rev-parse", "HEAD")})
            record("rebound_factory", [], [o["path"] for o in context["graph"]["operations"]],
                   "Plain decorator object does not register a FastAPI HTTP route")
        finally:
            store.close()
    return output

if __name__ == "__main__":
    import sys
    Path(sys.argv[1]).write_text(json.dumps(run(), indent=2) + "\n")
