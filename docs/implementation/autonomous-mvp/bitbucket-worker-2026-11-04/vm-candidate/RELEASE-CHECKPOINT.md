# Accepted source for three-system pilot

main c4053c6d4a959ff4d0e159c3cb1913fae87f25fb
tree 58103f677a545afe9ff3fa69919b1a5044ca3d2a, identical to qualified PR101.
PR101 4/4 CI PASS. Published archive acceptance completed 2026-11-07.

Release: https://github.com/rengalaxies/agent/releases/tag/agent-service-0.1.0-gc4053c6d4a95
Acceptance run: https://github.com/rengalaxies/agent/actions/runs/42395831851
All three jobs PASS: release, install-published (2/2), recovery-published (6/6).
Two builds identical; published download verified by workflow.

Archive: agent-service-0.1.0-gc4053c6d4a95-linux-x86_64-cp312.tar.gz
Archive SHA256: 69cee02353d64a4ba6044a6e121e373c191bac217bf4e48621980b2b8fd3367a
Manifest SHA256: 61b272693baae67aba8d91f2d618ba20297c26d94cee13facf60120ba42baaf8
Independent Mac download: both hashes PASS, embedded/published manifests identical,
all 78 manifest file hashes PASS, exact commit/tree verified.

These are CI lifecycle results, not installation on Cloud.ru. Deployment pin and
target VM remain unchanged. No GitHub platform immutable lock is asserted; release
identity is the archive digest plus exact manifest code SHA.

Release workflow agent-service-release.yml, ref main, input expected_main_sha
c4053c6d4a959ff4d0e159c3cb1913fae87f25fb. It must build twice identically,
verify downloaded published archive, and complete install/recovery gates.
Never overwrite a published release.

Target config includes Bitbucket jira_delivery, Confluence site and dry_run.
Target is separate agent-bitbucket.service on 127.0.0.1:8092.
After archive acceptance, fresh host inventory and backups precede installation.
Initialize dedicated bare mirrors, deliver authorized credentials privately,
validate import/config and permissions, start dry_run and check sources/results.
Then qualify restart, backup/restore and explicit live switch. Validate same
comment update, Confluence version change, removed link and API outage.
