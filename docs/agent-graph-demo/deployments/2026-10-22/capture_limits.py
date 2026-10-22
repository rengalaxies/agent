import json
from target_ui import OUT, remote

ids=remote('sudo -n docker ps -q').split()
assert all(len(i)==12 and all(c in '0123456789abcdef' for c in i) for i in ids)
objects=json.loads(remote('sudo -n docker inspect '+' '.join(ids))) if ids else []
result=[]
for c in objects:
    project=c['Config'].get('Labels',{}).get('com.docker.compose.project','')
    if project=='agent-graph-demo' or project.startswith('agent-graph-demo-sbx-'):
        h=c['HostConfig']
        result.append(dict(name=c['Name'],image=c['Image'],user=c['Config']['User'],
            project=project,memory=h['Memory'],nano_cpus=h['NanoCpus'],pids=h['PidsLimit'],
            readonly_rootfs=h['ReadonlyRootfs'],cap_drop=h['CapDrop'],security_opt=h['SecurityOpt'],
            restart=h['RestartPolicy'],log=h['LogConfig'],oom_killed=c['State']['OOMKilled'],
            mounts=[dict(destination=m['Destination'],read_write=m['RW'],type=m['Type']) for m in c['Mounts']]))
(OUT/'target-container-limits.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print([(r['name'],r['nano_cpus'],r['memory']) for r in result])
