"""Scoped recovery installer. Secrets are supplied only by the protected runner."""
import base64
import io
import ipaddress
import json
import os
import pathlib
import shlex
import subprocess
import time

import boto3
import paramiko
import requests
import yaml
from botocore.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROJECT = "20853297-65b7-42a8-af40-25c8d2df4e11"
OLD_UI = "1ddaa956-cfeb-4243-8007-1a4b7f715424"
CORE = "97a6e631-1d80-4212-aa69-ef6454b029df"
DISK = "9af43326-a6e1-45f1-8235-b82937a1f664"
ADDRESS = "cloudru_evolution_compute_vm.ui_vm"
ROOT = pathlib.Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "infra/cloudru/deploy"
TEMP = pathlib.Path(os.environ["RUNNER_TEMP"])
KEY_OBJECT = "deployment/p1/ui-recovery-key.pem"


def s3_client():
    assert os.environ["STATE_BUCKET"] == "test-bucket-ds"
    return boto3.client("s3", endpoint_url="https://s3.cloud.ru", region_name="ru-central-1",
                        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
                        config=Config(s3={"addressing_style": "path"}))


def prepare():
    sse = base64.b64decode(os.environ["AWS_SSE_CUSTOMER_KEY"], validate=True)
    assert len(sse) == 32
    client = s3_client()
    try:
        raw = client.get_object(Bucket=os.environ["STATE_BUCKET"], Key=KEY_OBJECT,
                                SSECustomerAlgorithm="AES256", SSECustomerKey=sse)["Body"].read()
    except client.exceptions.ClientError as error:
        assert error.response["Error"]["Code"] in ("NoSuchKey", "404"), "Cannot read installation key"
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                serialization.NoEncryption())
        if os.environ["RECOVERY_STAGE"] == "recover":
            client.put_object(Bucket=os.environ["STATE_BUCKET"], Key=KEY_OBJECT, Body=raw,
                              SSECustomerAlgorithm="AES256", SSECustomerKey=sse)
    for line in raw.decode().splitlines():
        print("::add-mask::" + line)
    key = serialization.load_ssh_private_key(raw, password=None)
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                         serialization.PublicFormat.OpenSSH).decode()
    path = TEMP / "installation-key"
    path.write_bytes(raw)
    path.chmod(0o600)
    response = requests.get("https://api.ipify.org", timeout=15)
    response.raise_for_status()
    address = ipaddress.ip_address(response.text.strip())
    assert address.version == 4 and address.is_global
    cidr = str(address) + "/32"
    print("::add-mask::" + str(address))
    print("::add-mask::" + cidr)
    with open(os.environ["GITHUB_ENV"], "a") as file:
        file.write("TF_VAR_deployment_public_key=" + public + "\n")
        file.write("TF_VAR_deployment_cidr=" + cidr + "\n")
    print("Installation key prepared; only its public half enters Terraform")


def state():
    result = subprocess.run(["terraform", "state", "pull"], cwd=DEPLOY,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def resources(document):
    result = {}
    for resource in document.get("resources", []):
        if resource["mode"] != "managed":
            continue
        for instance in resource.get("instances", []):
            attributes = instance["attributes"]
            if "project_id" in attributes:
                assert attributes["project_id"] == PROJECT
            result[(resource["type"], resource["name"], instance.get("index_key"))] = attributes
    return result


def plan():
    current = resources(state())
    core = current[("cloudru_evolution_compute_vm", "vm", "core")]
    assert core["id"] == CORE and core["name"] == "dm-p1-core"
    ui = current.get(("cloudru_evolution_compute_vm", "ui_vm", None)) or current.get(("cloudru_evolution_compute_vm", "vm", "ui"))
    if ui:
        assert ui["name"] == "dm-p1-ui"
    boot = current[("cloudru_evolution_compute_disk", "boot", "ui")]
    assert boot["id"] == DISK
    command = ["terraform", "plan", "-input=false", "-no-color", "-out=ui-recovery.tfplan"]
    if ui and ui["id"] == OLD_UI:
        command.append("-replace=" + ADDRESS)
    with (TEMP / "recovery-plan.log").open("w") as log:
        result = subprocess.run(command, cwd=DEPLOY, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((TEMP / "recovery-plan.log").read_text()[-8000:])
        raise SystemExit(result.returncode)
    result = subprocess.run(["terraform", "show", "-json", "ui-recovery.tfplan"], cwd=DEPLOY,
                            capture_output=True, text=True, check=True)
    changes = json.loads(result.stdout).get("resource_changes", [])
    new_nic = any(r["address"] == 'cloudru_evolution_compute_interface.nic["ui"]' and r["change"]["actions"] == ["create"] for r in changes)
    operations = []
    for resource in changes:
        change = resource["change"]
        if change["actions"] == ["no-op"]:
            continue
        before, after = change.get("before") or {}, change.get("after") or {}
        if resource["address"] == ADDRESS:
            assert change["actions"] in (["delete", "create"], ["create"])
            if before:
                assert before["id"] == OLD_UI and before["project_id"] == PROJECT
            assert after["project_id"] == PROJECT
            assert after["name"] == "dm-p1-ui"
            assert len(after["disks"]) == 1
            assert after["disks"][0]["id"] == DISK
            assert len(after["network_interfaces"]) == 1
            if new_nic:
                assert after["network_interfaces"][0].get("id") is None
            else:
                assert after["network_interfaces"][0]["id"] == current[("cloudru_evolution_compute_interface", "nic", "ui")]["id"]
            assert not after.get("cloud_init_userdata")
            assert after["image_metadata"]["name"]["string_value"] == "dmadmin"
        elif resource["address"] == 'cloudru_evolution_compute_interface.nic["ui"]':
            assert change["actions"] == ["create"] and not before
            assert after["project_id"] == PROJECT and after["name"] == "dm-p1-ui-nic"
            assert after["subnet"]["id"] == "d58e80ef-fff1-43eb-b601-96fb358224b7"
            assert after["security_groups"][0]["id"] == "4dde92a5-23a7-4c97-b48f-361d248b5af3"
            assert after["interface_security_enabled"] is True
        elif resource["address"] == "cloudru_evolution_compute_external_ip.ui":
            assert new_nic and change["actions"] == ["update"]
            assert before["id"] == after["id"] == "33a27f64-e474-49ed-a17b-15f67dd16400"
            assert before["project_id"] == after["project_id"] == PROJECT
            assert before["ip_address"] == after["ip_address"]
        elif resource["address"] == "cloudru_evolution_compute_security_group_rule.deployment_ui[0]":
            assert change["actions"] in (["create"], ["update"])
            assert after["security_group_id"] == "4dde92a5-23a7-4c97-b48f-361d248b5af3"
            assert after["remote_ip_prefix"] == os.environ["TF_VAR_deployment_cidr"]
            assert after["port_range"] == "22:22"
        else:
            raise AssertionError("STOP: unexpected change to " + resource["address"])
        operations.append((resource["address"], change["actions"]))
    print("UI_RECOVERY_PLAN_PASS", json.dumps(operations))
    print("Private core, all disks, both allocated IPs and NAT are retained; UI interface restoration is scoped to its original subnet and security group")


def connect(host, key, channel=None):
    client = paramiko.SSHClient()
    # First connection to this newly provisioned exact VM uses ordinary TOFU.
    # Host key is kept for every subsequent connection within the installation.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username="dmadmin", pkey=key, sock=channel, timeout=12,
                   banner_timeout=15, auth_timeout=15, allow_agent=False, look_for_keys=False)
    print("SSH authenticated to the approved UI VM")
    return client


def run(client, command, data=None, timeout=1200):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if data is not None:
        stdin.write(data)
        stdin.flush()
        stdin.channel.shutdown_write()
    # Read output while the process runs, rather than waiting on a full SSH buffer.
    for line in stdout:
        print(line.rstrip())
    errors = stderr.read().decode(errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        print(errors[-4000:])
        raise AssertionError("Remote installer failed with exit status " + str(status))


def bootstrap():
    current = state()
    data = resources(current)
    ui = data[("cloudru_evolution_compute_vm", "ui_vm", None)]
    assert ui["id"] != OLD_UI and ui["project_id"] == PROJECT
    assert data[("cloudru_evolution_compute_vm", "vm", "core")]["id"] == CORE
    assert data[("cloudru_evolution_compute_disk", "boot", "ui")]["id"] == DISK
    public_ip = data[("cloudru_evolution_compute_external_ip", "ui", None)]["ip_address"]
    core_ip = data[("cloudru_evolution_compute_interface", "nic", "core")]["ip_address"]
    key = paramiko.Ed25519Key.from_private_key_file(str(TEMP / "installation-key"))
    client = None
    for attempt in range(30):
        try:
            client = connect(public_ip, key)
            break
        except (OSError, paramiko.SSHException):
            print("Waiting for UI SSH startup", attempt + 1, "/30")
            time.sleep(10)
    assert client is not None, "UI SSH still unavailable after native image authentication configuration"
    owner_key = os.environ["TF_VAR_ssh_public_key"].strip()
    assert owner_key.startswith("ssh-ed25519 ") or owner_key.startswith("ssh-rsa ")
    run(client, "install -d -m 700 ~/.ssh; cat >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys", owner_key + "\n")
    values = {"ssh_public_key": json.dumps(owner_key), "git_ref": os.environ["TF_VAR_git_ref"],
              "core_ip": core_ip, "ui_ip_dashed": public_ip.replace(".", "-"),
              "ui_basic_auth_hash": os.environ["TF_VAR_ui_basic_auth_hash"].strip()}
    template = (ROOT / "infra/cloudru/bootstrap/ui-cloud-init.yaml").read_text()
    for name, value in values.items():
        template = template.replace("${" + name + "}", value)
    config = yaml.safe_load(template)
    packages = config["packages"] + ["qemu-guest-agent"]
    script = ["set -eu", "export DEBIAN_FRONTEND=noninteractive", "cloud-init status --wait >/dev/null 2>&1 || true",
              "apt-get update -qq", "apt-get install -y -qq " + " ".join(map(shlex.quote, packages))]
    for item in config["write_files"]:
        content = item["content"].replace("TimeoutStartSec=360", "TimeoutStartSec=1200")
        encoded = base64.b64encode(content.encode()).decode()
        destination = shlex.quote(item["path"])
        script += ["install -d " + shlex.quote(str(pathlib.Path(item["path"]).parent)),
                   "printf %s " + shlex.quote(encoded) + " | base64 -d > " + destination,
                   "chmod " + str(item["permissions"]) + " " + destination]
    script += ["systemctl enable --now qemu-guest-agent || true"]
    script += [" ".join(map(shlex.quote, command)) for command in config["runcmd"]]
    script += ["systemctl is-active caddy", "docker inspect -f '{{.State.Running}}' dmrp-ui"]
    run(client, "sudo -n /bin/bash -s", "\n".join(script) + "\n")
    run(client, "curl --silent --show-error --max-time 15 http://" + core_ip + ":8000/healthz || true")
    # Remove the installation credential after successful UI installation.
    # Owner key remains available only through the previously approved owner /32.
    public = key.get_name() + " " + key.get_base64()
    cleanup = "python3 -c " + shlex.quote("import pathlib; p=pathlib.Path.home()/'.ssh/authorized_keys'; lines=p.read_text().splitlines(); p.write_text('\\n'.join(x for x in lines if " + repr(public) + " not in x)+'\\n')")
    run(client, cleanup)
    client.close()
    print("UI installation completed; owner key retained and temporary installation key removed from OS")


def cleanup_plan():
    command = ["terraform", "plan", "-input=false", "-no-color", "-out=ui-cleanup.tfplan"]
    if os.environ.get("BOOTSTRAP_SUCCESS") != "true":
        # If VM creation failed, remove only the temporary SSH rule, without
        # implicitly attempting another VM/interface/IP recovery in cleanup.
        command.append("-target=cloudru_evolution_compute_security_group_rule.deployment_ui")
    result = subprocess.run(command,
                            cwd=DEPLOY, capture_output=True, text=True)
    if result.returncode:
        print(result.stdout[-4000:] + result.stderr[-4000:])
        raise SystemExit(result.returncode)
    document = json.loads(subprocess.run(["terraform", "show", "-json", "ui-cleanup.tfplan"],
                                        cwd=DEPLOY, capture_output=True, text=True, check=True).stdout)
    for resource in document.get("resource_changes", []):
        change = resource["change"]
        if change["actions"] == ["no-op"]:
            continue
        if resource["address"] == ADDRESS:
            assert change["actions"] == ["update"]
            before, after = change["before"], change["after"]
            assert before["project_id"] == after["project_id"] == PROJECT
            assert before["id"] == after["id"]
            differences = {k for k in before if before.get(k) != after.get(k)}
            assert differences <= {"image_metadata", "metadata_fields", "updated_at", "status", "guest_agent_state"}, differences
        elif resource["address"] == "cloudru_evolution_compute_security_group_rule.deployment_ui[0]":
            assert change["actions"] == ["delete"]
            assert change["before"]["security_group_id"] == "4dde92a5-23a7-4c97-b48f-361d248b5af3"
        else:
            raise AssertionError("Unexpected cleanup change: " + resource["address"])
    print("UI_CLEANUP_PLAN_PASS: remove runner /32 and restore owner public key metadata only")


if __name__ == "__main__":
    import sys
    {"prepare": prepare, "plan": plan, "bootstrap": bootstrap, "cleanup-plan": cleanup_plan}[sys.argv[1]]()
