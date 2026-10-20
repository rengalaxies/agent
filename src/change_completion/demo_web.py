"""Local synthetic product demo. Creates private credentials; no external sends."""
import argparse
import os
from pathlib import Path
import secrets

from .adapters import read_repository_file
from .run_cli import operator_path, read_operator_file
from .runtime import encode, run_transition
from .verification import load_json
from .web_api import create_product_app
from .web_server import bind_service
from .workflow_service import Principal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=".runtime/product-web")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--example", default=str(Path(__file__).resolve().parents[2] / "examples/product/execution"))
    args = parser.parse_args(argv)
    state, example = operator_path(args.state), operator_path(args.example)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    service = bind_service(example / "repository", example / "transition.json", example / "expectations.json",
                           example / "fixtures", example / "trust.json", state, worker_actor="demo-worker")
    result = run_transition(service.repository, service.spec_loader(), service.suite_loader(),
                            service.fixture_loader, service.policy_loader, service.runs, actor="demo-worker")
    if result["status"] != "READY_FOR_REVIEW":
        raise RuntimeError("demo transition unavailable; check fixture validity and installation")
    credentials = state / "demo-credentials.json"
    if not credentials.exists():
        actors = ("demo-worker", "analytics-owner", "audit-owner", "business-acceptor")
        fd = os.open(credentials, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encode({actor: secrets.token_urlsafe(32) for actor in actors}))
    values = load_json(read_operator_file(credentials))
    identities = {}
    for actor, token in values.items():
        permissions = {"read", "prepare_delivery"}
        permissions |= {"tick", "revalidate"} if actor == "demo-worker" else {"review"}
        identities[token] = Principal(actor, frozenset({service.spec_loader().transition_id}), frozenset(permissions))
    print("Local synthetic UI: http://127.0.0.1:"+str(args.port))
    print("Private role tokens: "+str(credentials)+" (not printed; copy one locally)")
    import uvicorn
    uvicorn.run(create_product_app(service, identities), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
