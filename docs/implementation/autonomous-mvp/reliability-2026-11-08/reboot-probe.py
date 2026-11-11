import pathlib,json,subprocess,pwd,urllib.request,urllib.error,shlex,time
cfg=json.loads(pathlib.Path('/etc/agent-bitbucket/service.json').read_text());u=pwd.getpwnam('agent-bitbucket')
code='import sqlite3,json,sys;c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True);c.row_factory=sqlite3.Row;print(json.dumps({"resources":[dict(r) for r in c.execute("select resource_id,generation,comment_id,published_generation from resources order by resource_id")],"jobs":dict(c.execute("select state,count(*) from jobs group by state")),"intents":dict(c.execute("select state,count(*) from intents group by state")),"checkpoints":dict(c.execute("select name,value from checkpoints"))}))'
r=subprocess.run(['/usr/bin/python3','-c',code,cfg['state_path']],user=u.pw_uid,group=u.pw_gid,extra_groups=[],capture_output=True,text=True,check=True)
report={'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'epoch':time.time(),'uptime':pathlib.Path('/proc/uptime').read_text().split()[0],'queue':json.loads(r.stdout),'publication':cfg['publication'],'loaded':json.loads(pathlib.Path('/var/lib/agent-bitbucket/run/loaded.json').read_text()),'units':{},'http':{}}
for unit in ['agent-service','agent-bitbucket','nginx','docker','ssh.socket']:
 report['units'][unit]=subprocess.check_output(['systemctl','is-active',unit],text=True).strip()
for port in [80,8080,18081,8091,8092]:
 url='http://127.0.0.1:'+str(port)+('/healthz' if port in [8091,8092] else '/')
 try:
  with urllib.request.urlopen(url,timeout=5) as r:report['http'][str(port)]=r.status
 except urllib.error.HTTPError as e:report['http'][str(port)]=e.code
 except OSError:report['http'][str(port)]=0
report['docker']=subprocess.check_output(['docker','ps','--format','{{.Names}} {{.Status}}'],text=True).splitlines()
env={k:shlex.split(v)[0] for k,v in (l.split('=',1) for l in pathlib.Path('/etc/agent-bitbucket/secrets.env').read_text().splitlines() if l and not l.startswith('#'))}
req=urllib.request.Request('http://127.0.0.1:8092/status',headers={'Authorization':'Bearer '+env['AGENT_SERVICE_STATUS_TOKEN']})
with urllib.request.urlopen(req,timeout=5) as r:report['status']=json.load(r)
pid=subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True).strip();report['systemd_pid']=int(pid);assert report['loaded']['pid']==int(pid)
print(json.dumps(report,indent=2))
