"""Run only through an already authenticated VM channel; no mutations or env dumps."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if result.returncode:
        return {"status": "BLOCKED", "exit_code": result.returncode}
    return {"status": "PASS", "value": result.stdout.strip()[:12000], "truncated": len(result.stdout)>12000}


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
report['host_identity']={'hostname':socket.gethostname(),'uid':os.getuid()}
report['network']={
 'addresses':command(['ip','-j','address','show']),
 'routes':command(['ip','-j','route','show','table','all']),
 'rules':command(['ip','-j','rule','show']),
 'rp_filter':command(['sysctl','net.ipv4.conf.all.rp_filter','net.ipv4.conf.default.rp_filter'])}
report['listeners']=command(['ss','-lnt'])
report['sudo_readonly']=command(['sudo','-n','id','-u'])
report['services']={name:command(['systemctl','is-active',name]) for name in ['ssh','docker','nginx']}
report['firewall']={name:command(args) for name,args in {
 'ufw':['sudo','-n','ufw','status','verbose'],
 'nft':['sudo','-n','nft','list','ruleset'],
 'iptables':['sudo','-n','iptables','-S'],
 'iptables_nat':['sudo','-n','iptables','-t','nat','-S']}.items() if shutil.which(args[2])}
report['runtime_access']={'git':command(['git','--version']),
 'security_options':command(['sudo','-n','docker','info','--format','{{json .SecurityOptions}}']),
 'cgroup_version':command(['sudo','-n','docker','info','--format','{{.CgroupVersion}}']),
 'root_filesystem':command(['findmnt','-n','-o','FSTYPE','/']),
 'root_docker_version':command(['sudo','-n','docker','version','--format','{{.Server.Version}}']),
 'root_containers':command(['sudo','-n','docker','ps','--format','{{.Names}} {{.Status}} {{.Ports}}']),
 'root_docker_usage':command(['sudo','-n','docker','system','df','--format','json'])}
print(json.dumps(report, indent=2))
