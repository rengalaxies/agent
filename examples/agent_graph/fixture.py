"""Synthetic inputs without a dependency map. Not an independent benchmark."""
from pathlib import Path
import hashlib
import shutil

from agent_graph.contracts import Policy


def create_fixture(directory):
    directory = Path(directory)
    shutil.copytree(Path(__file__).parent / "corpus", directory / "corpus")
    repositories = [dict(id=r, service=r, root=str(directory / "corpus" / r), revision="fixture-1")
                    for r in ("orders", "reporting", "export", "health")]
    sha = hashlib.sha256((directory / "corpus/reporting/business.md").read_bytes()).hexdigest()
    return Policy.model_validate(dict(
        installation_id="synthetic-demo", environment="test", subject="local-operator",
        capabilities=["read_context", "maintain", "propose", "report_check", "correct"],
        repositories=repositories,
        addresses=[dict(service="orders", base_url="https://orders.test"),
                   dict(service="inventory", base_url="https://inventory.test")],
        requirements=[dict(id="reporting-complete", repository="reporting", path="business.md",
                           sha256=sha, issuer="synthetic-operator-manifest", service="orders",
                           path_template="/orders", consumer="reporting", predicate="complete_collection")]))
