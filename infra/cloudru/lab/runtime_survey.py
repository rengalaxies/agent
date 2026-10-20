import json,subprocess,socket,os,pathlib,hashlib
SOURCE='107dfd14292a5ab06593d424bf0b94f1cccb0b90'
root='/home/dmadmin/agent-lab-staging/'+SOURCE+'/checkout'
def cmd(args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=30);return {'rc':p.returncode,'stdout':p.stdout[:12000],'stderr':p.stderr[:1000]}
r={'hostname':socket.gethostname(),'observed_source':os.environ['SSH_CONNECTION'].split()[0],'source':cmd(['git','-C',root,'rev-parse','HEAD']),'tree':cmd(['git','-C',root,'rev-parse','HEAD^{tree}']),'clean':cmd(['git','-C',root,'status','--porcelain']),'ports':cmd(['sudo','-n','ss','-lntp']),'containers':cmd(['sudo','-n','docker','ps','-a','--format','{{.Names}} {{.Status}} {{.Ports}}']),'caddy':cmd(['sh','-c','command -v caddy || true']),'nginx':cmd(['sudo','-n','nginx','-T']),'memory':cmd(['free','-b']),'disk':cmd(['df','-B1','/']),'dns':cmd(['getent','ahostsv4','45-151-31-140.sslip.io'])}
# Never print existing config auth material; retain structural lines only.
r['nginx']['stdout']='\n'.join(line for line in r['nginx']['stdout'].splitlines() if any(s in line for s in ['listen ','server_name ','root ','include ','proxy_pass ','auth_basic ']))
print(json.dumps(r))
