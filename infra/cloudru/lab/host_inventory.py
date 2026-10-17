"""Run only through an already authenticated VM channel; no mutations or env dumps."""
import json
import os
from pathlib import Path
import shutil
import subprocess


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if result.returncode:
        return {"status": "BLOCKED", "exit_code": result.returncode}
    return {"status": "PASS", "value": result.stdout.strip()}


memory = {}
for line in Path("/proc/meminfo").read_text().splitlines():
    key, value = line.split(":", 1)
    if key in {"MemTotal", "MemAvailable", "SwapFree"}:
        memory[key] = value.strip()
report = {"cpu_count": os.cpu_count(), "loadavg": list(os.getloadavg()), "memory": memory,
          "disk_root": dict(zip(("total", "used", "free"), shutil.disk_usage("/"))),
          "container_runtime": "NOT_MEASURED"}
if shutil.which("docker"):
    report["docker_version"] = command(["docker", "version", "--format", "{{.Server.Version}}"])
    report["compose_version"] = command(["docker", "compose", "version", "--short"])
    # No inspect/env or full logs: these can contain passwords.
    report["containers"] = command(["docker", "ps", "--format", "{{.Names}} {{.Status}}"])
    report["volume_names"] = command(["docker", "volume", "ls", "--format", "{{.Name}}"])
    report["container_runtime"] = "INVENTORIED"
print(json.dumps(report, indent=2))
