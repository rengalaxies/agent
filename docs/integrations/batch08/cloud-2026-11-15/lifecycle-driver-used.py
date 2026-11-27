import json,subprocess,time,sys
CONTROL='/tmp/impactmap08-cloud-control.py';HEAD='3883320d4725479f944298c322fa493dfc836457';CARD='74807549'
def call(*args):
 r=subprocess.run([sys.executable,CONTROL,*args],capture_output=True,text=True,timeout=90)
 try:v=json.loads(r.stdout)
 except ValueError:print(json.dumps({'action':args[0],'status':'CONTROL_FAILED','returncode':r.returncode}),flush=True);raise SystemExit(1)
 if r.returncode or v.get('status')=='FAIL':
  print(json.dumps({'action':args[0],'run':args[1] if len(args)>1 else None,'status':'FAIL','error_type':v.get('error_type'),'errors':v.get('errors'),'control':v if v.get('status')=='REMOTE_FAILED' else None}),flush=True);raise SystemExit(1)
 return v
def wait(name):
 deadline=time.monotonic()+240
 while time.monotonic()<deadline:
  v=call('receipt',name)
  if v.get('status')!='PENDING':
   print(json.dumps({'run':name,'status':v.get('status'),'generation':v.get('generation'),'comment_id':v.get('comment_id'),'steps':v.get('steps'),'closed':v.get('closed')}),flush=True)
   assert v.get('status')=='PASS';return v
  time.sleep(3)
 raise TimeoutError(name)
def run(name,card=CARD,closed=False):
 args=['run',name,HEAD,'ABSTAINED','none',card]
 if closed:args+=['closed']
 call(*args);return wait(name)
v=wait('corrected-replay');assert v['steps']==[]
for action,name,runid,closed in [('relink','secondary','relinked-secondary',False),('delete-result','secondary','recreated-secondary',False),('archive','secondary','archived-secondary',True),('restore','secondary','restored-secondary',False),('delete-card','secondary','deleted-secondary',True),('relink','primary','returned-primary',False)]:
 v=call(action,name);print(json.dumps({'action':action,'role':name,**v}),flush=True)
 run(runid,card='74759475' if name=='primary' else CARD,closed=closed)
print(json.dumps({'status':'ALL_LIFECYCLE_PHASES_PASS'}),flush=True)
