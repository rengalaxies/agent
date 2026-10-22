#!/bin/bash
set -euo pipefail
test "$(id -u)" = 0
systemctl disable --now agent-graph-demo-observe.timer
if test -f /var/lib/agent-graph-demo/runtime/active.json; then
  state=$(python3 -c 'import json;print(json.load(open("/var/lib/agent-graph-demo/runtime/active.json"))["state"])')
  gen=$(python3 -c 'import json;print(json.load(open("/var/lib/agent-graph-demo/runtime/active.json"))["generation"])')
  sid=$(python3 -c 'import json;print(json.load(open("/var/lib/agent-graph-demo/runtime/active.json")).get("session_id") or "")')
  if test "$state" = RUNNING; then
    /usr/local/sbin/agent-graph-demo-operator stop --session "$sid" --expected-generation "$gen"
  elif test "$state" != STOPPED; then
    /usr/local/sbin/agent-graph-demo-operator reconcile --expected-generation "$gen"
  fi
fi
systemctl disable --now agent-graph-demo.service
echo 'Demo stopped. Releases, image, credentials and history preserved. Old dmrp-ui/Nginx configuration was not changed; no need to restore or start the old failed service.'
echo 'To re-enable the same release: systemctl enable --now agent-graph-demo.service agent-graph-demo-observe.timer'
