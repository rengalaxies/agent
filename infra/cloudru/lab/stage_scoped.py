"""Use only a temporary current-runner /32 for fixed-source staging, then remove it."""
from scoped_ssh import main
from stage_release import main as stage

def deliver(tf,env,selected,resources):
 if stage()!=0:raise ValueError('RULE_EXACT_SOURCE_STAGING_FAILED')
 return {'action':'EXACT_SOURCE_STAGING','services_started':False,'sql_executed':False}
if __name__=='__main__':raise SystemExit(main(deliver))
