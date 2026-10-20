# Raven control and remaining network diagnosis

Observed on 2026-10-18, not inferred from supplied configuration. Read-only comparison run: https://github.com/rengalaxies/agent/actions/runs/39125410129 (commit 406776ee616a0381f5a0d2f2133b27467dbce200). Both targets were tested from the same Azure eastus Actions runner. No SSH authentication or cloud mutation was attempted on Raven.

| Check | Agent 45.151.31.140 | Raven 168.113.252.75 |
|---|---|---|
| TCP 22 | timeout | OpenSSH banner received |
| TCP 80 | timeout | HTTP 308 redirect |
| TCP 443 | timeout | connected |
| Trusted TLS with hostname verification | timeout | PASS, Let's Encrypt YE2, expires 2027-01-10 |

The Raven client-key fingerprint supplied by the owner identifies an authorized client, not an SSH server host key. It must not replace the target VM's independently pinned server key. The different Unix usernames and service directories are normal project-specific choices. Opening SSH to 0.0.0.0/0 is unnecessary and prohibited for this target.

Target run https://github.com/rengalaxies/agent/actions/runs/39125140553/attempts/1 independently confirmed running VM, current FIP/NIC/SG attachment and created its own runner TCP22 /32. Source observation was 135.232.177.114. All 24 TCP attempts timed out over 188.11 seconds, before host-key negotiation and authentication. Its own rule was removed; actual final SG audit passed: one operator /32, public 80/443, no broad administrative rule. The unprivileged runtime was not reached in that attempt.

This demonstrates a pre-authentication reachability failure. The public port-80 control cannot be explained by a mismatched SSH client key or an absent HTTPS proxy. It does not alone distinguish provider dataplane filtering, FIP/return routing, a source-route mismatch, or current guest filtering. Earlier successful pinned/authenticated OS surveys are historical evidence, not proof of the present guest state. A packet trace at the guest interface is the next discriminating observation.

## Browser console checks, no client installation

Open the existing dm-p1-ui VM's Cloud.ru browser console. Run separately:

```
hostname
ip -br address
ip route
sudo ss -lntp
sudo iptables -nvL INPUT
sudo nft list ruleset
```

If tcpdump is already present, run while a coordinated external probe is active:

```
sudo timeout 30 tcpdump -ni enp3s0 -c 20 'tcp port 22 or tcp port 80 or tcp port 443'
```

No incoming SYN suggests a failure before the guest; incoming SYN without a reply directs investigation to guest listeners/filtering; outgoing SYN-ACK without client connection directs investigation to the return path. These are diagnostic branches, not current conclusions. Do not change routes/firewall blindly or disable SSH host-key checks. Browser automation did not obtain a console session; it timed out and is not being used again in this pass.

## Targeted support request (draft, not sent)

Project 20853297-65b7-42a8-af40-25c8d2df4e11, ru.AZ-2. Existing VM c9e589fc-a42a-4cc3-8038-fe7d73929713 (dm-p1-ui), NIC 7415eae4-918b-4784-b4b2-a19325f976b6, private 10.0.0.6, FIP 45.151.31.140 allocation 33a27f64-e474-49ed-a17b-15f67dd16400, SG 4dde92a5-23a7-4c97-b48f-361d248b5af3.

Please trace incoming SYN and return traffic through the public FIP mapping and applied security-group dataplane. At 2026-10-18 11:56-12:01 UTC the attached VM was reported running and the exact runner 135.232.177.114/32 TCP22 rule was successfully created, but 24 connection attempts timed out before SSH negotiation. The temporary rule was subsequently deleted. At 11:59:11 UTC, a separate same-runner comparison found this target's public TCP80 unreachable while Raven 168.113.252.75 responded on 22/80/443 and presented trusted HTTPS. Target public 80/443 remain allowed according to a fresh API rule audit. Please verify actual FIP DNAT/SNAT, SG propagation and return routing rather than SSH authorized_keys. Evidence is linked above. No request to widen SSH, recreate the VM or change tariffs.
