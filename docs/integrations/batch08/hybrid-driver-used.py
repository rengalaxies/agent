import json,shutil,subprocess
from pathlib import Path
from agent_service.config import build,ServiceConfig,core_analyzer
from agent_service.service import Service
from tests.service import test_bitbucket_analysis as fixture

root=Path('work/batch08/hybrid-v1').resolve();root.mkdir(exist_ok=True)
private=Path('work/batch08/private');setup=json.loads((private/'setup.json').read_text());card=json.loads((private/'card-create.json').read_text())
f=fixture.WorkerTest();f.setUp()
analyzer=None
try:
 if not (root/'repos').exists(): shutil.copytree(f.f.root/'repos',root/'repos')
 policy=json.loads(Path(f.f.document['core']['policy_path']).read_text())
 for repo in policy['repositories']: repo['root']=str(root/'repos'/repo['id'])
 (root/'policy.json').write_text(json.dumps(policy,indent=2)+'\n')
 config=dict(f.f.document)
 config['bitbucket']=dict(config['bitbucket'],mode='kaiten_delivery')
 config.update(state_path=str(root/'service.sqlite'),core={'policy_path':str(root/'policy.json'),'state_dir':str(root/'core')},publication='live',kaiten={'base_url':'https://rengalaxies.kaiten.ru','board_ids':[setup['board_id']],'bot_id':setup['bot_id'],'token_env':'IM_KAITEN_TOKEN','bindings':{f.rid:card['card_id']}})
 cfg=ServiceConfig.model_validate(config)
 secrets=dict(f.f.secrets);secrets['IM_KAITEN_TOKEN']=(private/'kaiten-token.txt').read_text().strip()
 store,connectors,backends=build(cfg,env_secret=secrets.__getitem__)
 analyzer=core_analyzer(cfg.core,code_version='batch08-candidate')
 service=Service(store=store,connectors=connectors,backends=backends,analyzer=analyzer,installation_id='impactmap-batch08-authored-hybrid',environment='author-hybrid-not-live-bitbucket')
 def cycle():
  service.reconcile();steps=service.run_until_idle();return steps
 existing=store.resource(f.rid)
 if existing is not None: assert existing['snapshot']['head_sha']==f.head, 'Refuse mismatched resume source'
 first_steps=cycle(); first=store.jobs(f.rid)[-1]; first_intent=store.intents(f.rid)[-1]
 assert first['state']=='DONE' and first_intent['state']=='DELIVERED', (first['state'],first_intent['state'])
 assert any(x['code']=='POSSIBLE_TRUNCATION' for x in first['result']['findings'])
 cid=store.resource(f.rid)['comment_id']; assert cycle()==[]
 orders=root/'repos'/'orders'
 head=subprocess.check_output(['git','-C',str(orders),'-c','user.name=ImpactMap author fixture','-c','user.email=fixture@example.invalid','commit-tree',f.pins['orders']+'^{tree}','-p',f.head,'-m','Restore original API default in authored fixture'],text=True).strip()
 subprocess.run(['git','-C',str(orders),'update-ref','refs/heads/pilot-page-limit',head],check=True)
 f.pr['source']['commit']['hash']=head
 second_steps=cycle();second=store.jobs(f.rid)[-1];second_intent=store.intents(f.rid)[-1]
 assert second['state']=='DONE' and second_intent['state']=='DELIVERED'
 assert not any(x['code']=='POSSIBLE_TRUNCATION' for x in second['result']['findings'])
 assert store.resource(f.rid)['comment_id']==cid
 assert cycle()==[]
 reopened,con2,back2=build(cfg,env_secret=secrets.__getitem__)
 restarted=Service(store=reopened,connectors=con2,backends=back2,analyzer=analyzer,installation_id='impactmap-batch08-authored-hybrid',environment='author-hybrid-not-live-bitbucket')
 restarted.recover();restarted.reconcile();assert restarted.run_until_idle()==[]
 comments=con2['bitbucket'].kaiten.list_comments(card['card_id'])
 owned=[c for c in comments if c.marker==second_intent['marker'] and c.author==setup['bot_id']]
 assert len(owned)==1
 result={'status':'PASS','provenance':'AUTHORED_LOCAL_BITBUCKET_HTTP_AND_GIT_REAL_CORE_REAL_KAITEN','real_cloud_bitbucket':False,'real_kaiten':True,'model':'OFF','installation':'impactmap-batch08-authored-hybrid','target':{'tenant':'https://rengalaxies.kaiten.ru','board_id':setup['board_id'],'card_id':card['card_id']},'resource':f.rid,'first':{'generation':first['generation'],'status':first['result']['status'],'findings':[x['code'] for x in first['result']['findings']],'head':f.head,'steps':first_steps},'corrected':{'generation':second['generation'],'status':second['result']['status'],'reason':second['result']['reason_code'],'findings':[x['code'] for x in second['result']['findings']],'head':head,'steps':second_steps},'same_scoped_comment_id':cid,'native_comment_id':owned[0].comment_id,'owned_marker_count':len(owned),'repeat_idle':True,'store_reconstructed_idle':True,'process_restart':False,'production_deployment':False}
 (root/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False))
finally:
 if analyzer: analyzer.close()
 f.doCleanups()
