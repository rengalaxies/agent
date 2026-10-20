# Contract consumer profile: independent checks across technology boundaries

This is a second, replaceable execution profile. It demonstrates JSON input
contracts, bounded Python consumer mappings and real SQL result materialization.
It does not constrain the product architecture to these technologies.

The producer supplies integer rubles. Finance must receive integer kopecks;
audit must retain integer rubles. A blanket adaptation is wrong. Independently
written approval fixtures cover normal values, refunds, zero and duplicate rows.
The source repository is never modified by generation or checking.

## What executes

A trusted Python adapter validates and interprets a canonical Python consumer
file. Only direct integer field mapping and positive integer scaling are supported.
No candidate-controlled Python module is imported or executed. Contract fields,
integer limits and row counts are checked. Floats, booleans used as integers,
overflow, unsupported Python and unsupported SQL stop the run. The materialized
rows then pass to the existing isolated, restricted SQLite SELECT worker.

Consumer `.py` files are real valid Python, but the executor deliberately supports
only this canonical subset. This is not an arbitrary application-code sandbox.
The contract unit is explicit metadata; the approved consumer expectations define
what business result is accepted. The engine does not infer correct business units.

## Generate and check

Run from the repository root with `PYTHONPATH=src`. Choose fresh output paths;
commands refuse overwrites. Example paths below are scratch outputs, outside the
baseline directory.

```sh
python -m change_completion.contract_cli generate \
  --source examples/product/contract_change/baseline \
  --changes examples/product/contract_change/changes.json \
  --output /tmp/contract-candidate

python -m change_completion.contract_cli check \
  --repository /tmp/contract-candidate \
  --suite examples/product/contract_change/approval/suite.json \
  --approved-suite-sha256 4b0f8e4824b554fdae05068de6b891d2932cbf884f2a3e82980ff8cc74fbce7f
```

Use the digest in `approval/suite.sha256` if this example's fixtures change after
review. In a real installation the operator must pin the suite and digest in a
protected CI variable or independent approval repository. Calculating an approval
digest from the candidate checkout during CI would defeat independence.

The check returns exit code 0 only for PASS; FAIL and STOP return 1. The old
baseline fails the new finance requirement. Generate with `negative-changes.json`
to demonstrate that converting audit as well fails independent audit expectations.
PASS describes these declared fixtures and consumers, never full discovery or
production release authorization.

## Offline Git review package

```sh
python -m change_completion.contract_cli bundle \
  --baseline examples/product/contract_change/baseline \
  --candidate /tmp/contract-candidate \
  --paths profile.json contract.json finance.py finance.sql audit.py audit.sql \
  --output /tmp/contract-review
```

The package contains `candidate.patch` and an independently cloneable
`candidate.bundle` with baseline and candidate commits. Source directories do not
need to be Git repositories. Git runs in an isolated temporary repository, with
empty hooks, fixed offline author, no global/system configuration and no remote.
Only explicitly named files are exported. Export itself does not approve content.
A reviewer can clone the bundle and run the same check command against the clone,
using the independently protected suite and digest.

A protected CI job should execute the check command on the proposed branch,
with its own trusted version of this verifier. Deny modifications to the job,
approval suite, digest and verifier through the candidate's own approval rights.
The job must fail on either FAIL or STOP. No hosted GitLab/GitHub connection or
external PR was created by this example.

## Boundaries

- Only declared consumers are covered; no runtime consumer discovery.
- This CLI profile is not yet wired into the product UI and task queue.
- No arbitrary Python, live API calls, production deployment, cutover or retirement.
- Operator approval, authority grants and environment qualification remain separate.
- Git bundle exports permit review and CI replay; they do not merge or deploy.
