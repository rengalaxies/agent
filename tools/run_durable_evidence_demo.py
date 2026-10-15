"""Reproducible synthetic durable lifecycle; writes only the chosen output dir."""
import argparse
import json
from pathlib import Path
from datamesh_release_protocol.evidence_pilot import SyntheticPilot

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
directory = args.output / 'state'
if (directory / 'pilot-ledger.json').exists():
    raise ValueError('choose a fresh output directory; existing approval history must not be reset')
pilot = SyntheticPilot(directory)
initial = pilot.state()
pilot.action('authorize')
unconfirmed = pilot.state()
pilot.action('approve')
committed = pilot.action('authorize')
restarted = SyntheticPilot(directory)
after_restart = restarted.state()
restarted.action('revoke')
restored_after_revoke = SyntheticPilot(directory)
blocked = restored_after_revoke.action('authorize')
assert initial['current_evidence_decision'] == 'NEEDS_REVIEW'
assert unconfirmed['last_decision']['release_id'] is None
assert committed['last_decision']['terminal_state'] == 'COMMITTED'
assert after_restart['last_decision'] == committed['last_decision']
assert blocked['last_decision']['release_id'] is None
assert blocked['historical_authorizations'] == 1
result = dict(kind='synthetic-posix-durable-lifecycle-not-production-deployment',
              initial=initial, before_approvals=unconfirmed, authorized=committed,
              after_restart=after_restart, revoked_after_restart=blocked,
              physical_publication=False)
(args.output / 'lifecycle.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'authorized': committed['last_decision']['terminal_state'],
                  'after_restart': after_restart['last_decision']['terminal_state'],
                  'after_revocation': blocked['last_decision']['terminal_state'],
                  'historical_authorizations': blocked['historical_authorizations']}))
