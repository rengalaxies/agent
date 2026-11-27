"""Local author-fixture UI audit only. Never use with a real deployment/config."""
import base64
import json
from pathlib import Path
import uvicorn
from agent_graph_demo.api import create_app
from tests.graph_demo.helpers import DemoCase
from tests.service.test_graph_memory import GraphCase
from agent_service.api import create_app as service_app

root = Path(__file__).resolve().parents[4]
demo = DemoCase()
demo.setUp()
demo.settings.start_worker = True
demo.settings.allowed_origins = ["http://127.0.0.1:18086"]
demo.settings.product_sha = "c82dd59-A6-AUTHOR-FIXTURE"
demo_app = create_app(demo.settings)
case = GraphCase()
case.setUp()
comment = case.jira_comment()
service = service_app(case.bench.service, status_token="local-audit-fixture")
out = root / "docs/product/ui-admin-2026-11-16"
out.mkdir(parents=True, exist_ok=True)
(out / "fixture-comment.txt").write_text(comment)
(out / "fixture-result.json").write_text(json.dumps(case.bench.service.store.resource_diagnostics("jira:10012"), ensure_ascii=False, indent=2))

async def app(scope, receive, send):
    # Only in this disposable loopback fixture: pre-authenticate its author user.
    scope = dict(scope)
    headers = [(k, v) for k, v in scope.get("headers", []) if k != b"authorization"]
    is_service = scope.get("path", "").startswith(("/graph", "/resources", "/result", "/status", "/healthz"))
    token = b"Bearer local-audit-fixture" if is_service else b"Basic " + base64.b64encode(b"operator:test-password")
    scope["headers"] = headers + [(b"authorization", token)]
    await (service if is_service else demo_app)(scope, receive, send)

try:
    uvicorn.run(app, host="127.0.0.1", port=18086, access_log=False)
finally:
    case.doCleanups()
    demo.doCleanups()
