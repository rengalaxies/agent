# IP replacement preparation — 2026-11-08

Support ticket 481573 (engineer reply 16:30 Moscow) attributes current IP problems to TSPU and recommends replacing the IP followed by `sudo cloud-init clean` and `sudo cloud-init init`.
Reference: https://cloud.ru/docs/overview/tutorials/topics/diagnostics

Existing floating IP: 45.151.31.140, resource 33a27f64-e474-49ed-a17b-15f67dd16400.
VM dm-p1-ui: c9e589fc-a42a-4cc3-8038-fe7d73929713, internal 10.0.0.6, ru.AZ-2.

Before any changes, created on-VM root-owned directory /var/backups/ip-change-20261108 (0700), archive config.tgz (0600), containing /etc/cloud, /var/lib/cloud, /etc/netplan, /etc/ssh, /etc/agent-bitbucket and /etc/agent-service. `gzip -t` returned without errors. This is a configuration backup, not an application-state restore test. Secret contents remain on the VM.

Prepared rental form: dm-p1-ui-replacement-20261108, ru.AZ-2. UI price 149.33 RUB/month, VAT included, charged hourly. No address rented or detached yet. Awaiting explicit cost approval under owner's prior restriction on new paid resources. Proposed temporary overlap retains the old IP for rollback; permanent release of the old IP requires separate action-time confirmation.

cloud-init clean/init NOT_RUN. They can replay initialization, including SSH/network configuration; review installed cloud-init config/modules and private user-data before execution, preserve SSH host identity where possible, and validate current host keys from VNC before accepting any change. Do not disable host-key verification. Do not apply the stale Terraform plan. VPN remains unchanged by explicit prohibition.

After approval: allocate only the prepared replacement IP, record address and ID, switch binding without adding ports, execute reviewed support remediation with protected logs, verify VNC/SSH host identity, outbound GitHub/Jira/Bitbucket and existing worker/demo health. Update local SSH HostName and affected references only after actual connectivity validation. Keep old IP available until the new path is qualified.

## Allocation checkpoint

Owner approved rental and replacement, and requested release of the old address after successful validation.
Allocated 82.202.141.50, ID a7740de0-5c54-416c-b1ad-8b90011bb3a2, name dm-p1-ui-replacement-20261108, ru.AZ-2. It is currently FREE/UNASSIGNED and BILLABLE; do not leave forgotten. Original address remains assigned.

Automatic approval rejected the attempt to detach the original IP before validating the replacement, interpreting the owner's condition as prohibiting interruption. No detach occurred. Safer direct assignment was inspected: choosing floating IP lists only dm-p1-core, not the occupied dm-p1-ui. No other VM was selected or modified. Requested explicit owner clarification permitting temporary detachment while retaining the old IP in rental for rollback. Awaiting response. No cloud-init command executed.

## Successful switch

Owner explicitly approved the temporary disconnection. Detached old address without releasing rental, then assigned 82.202.141.50 to dm-p1-ui interface 10.0.0.6 via VM Network settings. Global floating-IP resource selector omitted the target even after detach; direct interface assignment worked. Other VM and NAT gateway untouched.

Executed cloud-init clean and cloud-init init under root with a protected log at /var/backups/ip-change-20261108/reinit.log. Both exited 0. Added /etc/cloud/cloud.cfg.d/99-preserve-existing-hostkeys.cfg with ssh_deletekeys:false before init. Compared SHA256 of private host-key files before/after: unchanged. No private key values output. Inspected user-data keys and bootcmd; bootcmd configures provider apt mirrors.

cloud-init changed OS hostname to vm-c9e589fc-a42a-4cc3-8038-fe7d73929713. Restored dm-p1-ui with hostnamectl and added preserve_hostname:true to the preservation config. Cloud resource name unchanged. No reboot.

SSH to new IP passed StrictHostKeyChecking with old pinned key via HostKeyAlias 45.151.31.140. Active local profile updated to new HostName, with private config backup config.before-ip-replacement-20261108.

Fresh HTTPS from VM: api.github.com 200, github.com 200, raw.githubusercontent.com 200, api.bitbucket.org 200; Jira site responded 202. These are transport/read probes, not a new integration acceptance.

Fresh runtime proof: ip-change-runtime.json. agent-service, agent-bitbucket, nginx, docker, ssh.socket active. Loopback HTTP 80/8080/8091/8092=200; protected demo 18081=401 as expected. Both demo containers running, dmrp-ui healthy. Queue counters preserved (ANALYZED1/DONE8/SUPERSEDED1), status notices empty. Bitbucket worker remains c4053c6; formatter update NOT_RUN.

Old address 45.151.31.140 is now FREE and still BILLABLE. Prepared final release modal; user asked for action-time confirmation because it irreversibly returns the address to the allocation pool. Awaiting answer. New IP fully qualified for connectivity; VPN and security-group rules unchanged.

## Old address released

Owner explicitly confirmed irreversible release at action time. Cloud.ru confirmed "Публичный IP успешно удален" for old resource 33a27f64-e474-49ed-a17b-15f67dd16400 / 45.151.31.140; old row disappeared and IP quota became available. Per confirmation dialog, rental billing stops. New 82.202.141.50 remains assigned to dm-p1-ui. Existing NAT gateway address untouched. Screenshot /tmp/cloudru-old-ip-released.png. Rollback to the same old IP is no longer available; configuration backup remains on VM. Historical HostKeyAlias retains only the pinned identity label, not a network connection to the released address.
