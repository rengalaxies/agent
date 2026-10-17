#!/bin/sh
# Install this job from a protected location, not the proposed candidate branch.
set -eu
: "${APPROVED_SUITE_PATH:?operator-managed independent suite path required}"
: "${APPROVED_SUITE_SHA256:?protected approval digest required}"
if [ "$#" -ne 1 ]; then
  echo 'Usage: ci-check.sh CANDIDATE_CHECKOUT' >&2
  exit 2
fi
exec python -m change_completion.contract_cli check \
  --repository "$1" \
  --suite "$APPROVED_SUITE_PATH" \
  --approved-suite-sha256 "$APPROVED_SUITE_SHA256"
