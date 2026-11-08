# Rollout checkpoint — 2026-11-08

PR #103 merged after all four workflows passed for exact head
`53fa40fdc0f67d502141ed51e3ddc56efeb1c23a`.
Merge SHA: `a02ffa7854dcc38cecc7fe5c5317466059926cd9`.
Merge tree equals qualified PR tree: `fcea076ef74c057d95f9d21103ba15e6fd94858c`.

Immutable release workflow dispatched on main with this exact expected_main_sha:
https://github.com/rengalaxies/agent/actions/runs/42479463480

Release and install-published: PASS. Recovery-published: PASS.
Downloaded archive, manifest, full tree and wheels independently verified: PASS.
See release-verification.json for SHA256 values.

Cloud.ru reports dm-p1-ui running. VNC successfully shows Ubuntu 24.04.4 LTS login on tty1.
No saved OS password found in the established SSH profile. Owner logged into VNC. Fresh probe confirms ssh.socket, ssh.service, agent-bitbucket, nginx active; worker healthz returns live=true; 22G disk and 3297 MiB memory available.
Direct TCP probe receives EOF before SSH banner; HTTP request also closes without response.
Latest direct SSH attempt absent from latest sshd log. Mac route uses VPN utun5.
VPN path is suspected, not proven; temporary VPN-change approval requested.
No network/security changes, host service changes, or reboot attempted.

## Target host

Fresh SSH preflight and two retries failed before authentication:
`kex_exchange_identification: Connection closed by remote host`.
TCP port 22 accepts a connection, then closes before the remote SSH banner/key exchange.
This is not evidence of a credential failure or a running application failure.
No host changes were made in this iteration. VM rollout and Jira comment refresh: NOT_RUN.
Last previously verified worker release: c4053c6; current runtime state could not be rechecked.

## Resume

1. Require release, install-published and recovery-published success; verify downloaded archive/manifest.
2. Restore SSH access without bypassing pinned host-key checking; inspect host before changes.
3. Take matching config/state/core backup, retaining current valid secrets.
4. Stage verified release alongside current worker; check state/core compatibility.
5. Stop only agent-bitbucket.service; set jira.comment_format=summary_ru and new code_version;
   atomically activate release. Reopen Bitbucket resources through ServiceStore API while stopped.
6. Start worker and verify loaded SHA, non-root UID, model OFF, status/logs, persistence.
7. Verify KAN-9 comment 10046 is updated in place with Russian summary and Confluence title/version/link,
   while full neutral analysis remains stored. Confirm unrelated demo/services unchanged.
8. If failure before publication, restore matching config/symlink/state backup. After external writes,
   preserve current delivery receipts and inspect comments before any state rewind.

## VNC continuation

Owner forbids disabling VPN; no VPN, route or security setting changed.
Prepared explicit rollout helper on branch codex/jira-summary-vm-rollout,
commit 52c3246a09066822ba17a85644d50eac10d75907.
Helper SHA256: c611f9d617ec6fa28a7fe48dd5759ecc65d559633870ef1e77655ade45f20585.
Only local syntax validation performed; activation path is not target-qualified.
A VNC curl request for this pinned raw file did not complete. No script executed.
Attempted control-key interruption did not produce a shell prompt; owner asked to
interrupt the curl in the terminal. No backup, stage, activation, configuration change,
worker stop or Jira reprocessing occurred in this continuation.
Do not run activate before reviewing and verifying a matching restorable backup.

VNC interruption resolved using the Control panel button followed by a key targeted at the VNC image. Shell prompt confirmed. Retried curl with IPv4 and --max-time 20. VPN unchanged.

VNC continuation: raw GitHub and GitHub API TCP timeouts reproduced; DNS resolves and route present. Cloud.ru still maps 45.151.31.140 to 10.0.0.6, outgoing group allows any IPv4; OS OUTPUT ACCEPT and UFW inactive. Public Jira HTTPS returned 302, so a global outbound outage is not established. Downloaded public pinned helper through jsDelivr; on-VM SHA256 exactly c611f9d617ec6fa28a7fe48dd5759ecc65d559633870ef1e77655ade45f20585. Started stage only with external timeout 90; awaiting result.

## Final VNC checkpoint

Pinned helper delivered through jsDelivr and SHA256 confirmed on the VM.
Stage invocation returned to shell after timeout; staging directory listing `total 0`.
No archive, verified stage, backup, activation or reprocessing completed.
GitHub API resolves to 140.82.121.5; TCP 443 connect timed out in 5 seconds.
Raw GitHub and API blob attempts timed out in 20 seconds. Jira public HTTPS returned 302.
Cloud security-group outbound permits any IPv4; host OUTPUT policy ACCEPT, UFW inactive.
A direct public release-asset CDN URL was attempted but VNC character loss corrupted
its hostname. Do NOT interpret its DNS error as proof of a DNS/provider outage.
The partial long command was explicitly cancelled before submission; the subsequent
complete attempt failed before transfer. No TLS or host-key verification disabled.
A history substitution attempt selected an older read-only journalctl command
because leading-space commands were excluded from shell history; no service change.
Final worker health probe returned live=true and systemctl is-active returned active.
Target update remains NOT_RUN. Main release is accepted; target archive delivery is blocked.
Resume with a reliable file delivery channel or validated short bootstrap URL, rather
than manually typing another long signed asset URL. Do not alter the prohibited VPN.
