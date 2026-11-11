"""Run on target via sudo python3; never prints the private status token."""
import json
from pathlib import Path
from urllib.request import Request, urlopen
values = dict(line.split("=", 1) for line in Path("/etc/agent-bitbucket/secrets.env").read_text().splitlines())
request = Request("http://127.0.0.1:8092/status", headers={"Authorization": "Bearer " + json.loads(values["AGENT_SERVICE_STATUS_TOKEN"])})
with urlopen(request, timeout=10) as response:
    print(json.dumps(json.load(response), indent=2))
