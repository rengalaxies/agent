"""Read only the existing approved state and exact VMs; emit an allowlisted report.

No Terraform init/apply, VM actions, broad project inventory or remote execution.
State and API responses remain in memory, never in logs or artifacts.
"""
import base64
import json
import hashlib
import io
import logging
import tempfile
import os
from pathlib import Path
import socket
import sys
from datetime import datetime, timezone

PROJECT = "20853297-65b7-42a8-af40-25c8d2df4e11"
TENANT = "fc91c42d-c2ea-4d6d-a236-103fd1f37f00"
REQUIRED = ["CLOUDRU_KEY_ID", "CLOUDRU_SECRET", "CLOUDRU_STATE_SSE_CUSTOMER_KEY"]
PRESENCE = REQUIRED + ["CLOUDRU_STATE_ACCESS_KEY_ID", "CLOUDRU_STATE_SECRET_ACCESS_KEY",
    "CLOUDRU_SSH_PUBLIC_KEY", "CLOUDRU_UI_BASIC_AUTH_HASH", "CLOUDRU_WORKFLOW_API_KEY",
    "CLOUDRU_LAB_SSH_PRIVATE_KEY", "CLOUDRU_LAB_SSH_KNOWN_HOSTS", "CLOUDRU_LLM_API_KEY", "CLOUDRU_FOUNDATION_API_KEY"]


def select_state(state):
    if not state.get("lineage") or not isinstance(state.get("serial"), int):
        raise ValueError("STATE_IDENTITY_MISSING")
    managed = {}
    for resource in state.get("resources", []):
        if resource.get("mode") != "managed":
            continue
        for instance in resource.get("instances", []):
            attrs = instance["attributes"]
            if "project_id" in attrs and attrs["project_id"] != PROJECT:
                raise ValueError("STATE_PROJECT_MISMATCH")
            managed[(resource["type"], resource["name"], instance.get("index_key"))] = attrs
    result = {}
    for label, key in [("ui", ("cloudru_evolution_compute_vm", "ui_vm", None)),
                       ("core", ("cloudru_evolution_compute_vm", "vm", "core"))]:
        vm = managed[key]
        if vm.get("project_id") != PROJECT or vm.get("name") != "dm-p1-" + label:
            raise ValueError("VM_IDENTITY_MISMATCH")
        if live_zone_name(vm) != "ru.AZ-2":
            raise ValueError("VM_ZONE_MISMATCH")
        result[label] = vm
    if result["core"]["id"] != "97a6e631-1d80-4212-aa69-ef6454b029df":
        raise ValueError("CORE_ID_MISMATCH")
    ip = managed[("cloudru_evolution_compute_external_ip", "ui", None)]
    if ip.get("id") != "33a27f64-e474-49ed-a17b-15f67dd16400":
        raise ValueError("PUBLIC_IP_ID_MISMATCH")
    nic = managed[("cloudru_evolution_compute_interface", "nic", "ui")]
    if ip.get("network_interface", {}).get("id") != nic["id"]:
        raise ValueError("PUBLIC_IP_INTERFACE_MISMATCH")
    result["ui_nic_id"] = nic["id"]
    result["ui_ip"] = ip["ip_address"]
    return result


def live_zone_name(vm):
    zone = vm.get("availability_zone") or vm.get("zone") or {}
    return zone.get("name") if isinstance(zone, dict) else zone


def probe(host, port):
    try:
        with socket.create_connection((host, port), timeout=6):
            return "TCP_CONNECTED"
    except OSError:
        return "TCP_UNREACHABLE"


def ssh_probe(host, private_key=None):
    """Public handshake only unless trusted known_hosts is supplied beforehand."""
    import paramiko
    logging.getLogger("paramiko").disabled = True
    transport = None
    result = {"authentication": "NOT_ATTEMPTED", "host_trust": "UNVERIFIED"}
    try:
        sock = socket.create_connection((host, 22), timeout=8)
        transport = paramiko.Transport(sock)
        transport.banner_timeout = 8
        transport.start_client(timeout=10)
        key = transport.get_remote_server_key()
        result["observed_host_key_sha256"] = "SHA256:" + base64.b64encode(
            hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        result["observed_host_key_type"] = key.get_name()
        transport.close()
        transport = None
        known = os.getenv("CLOUDRU_LAB_SSH_KNOWN_HOSTS", "").strip()
        if not known:
            result["status"] = "BLOCKED_HOST_TRUST_UNVERIFIED"
            return result
        if not private_key:
            result["status"] = "BLOCKED_NO_VERIFIED_CREDENTIAL"
            return result
        # Never promote the observed key to trust. Use only preconfigured entries.
        with tempfile.TemporaryDirectory() as directory:
            known_path = Path(directory) / "known_hosts"
            known_path.write_text(known + "\n")
            known_path.chmod(0o600)
            with paramiko.SSHClient() as client:
                client.load_host_keys(str(known_path))
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                private = paramiko.Ed25519Key.from_private_key(io.StringIO(private_key.decode()))
                client.connect(host, username="dmadmin", pkey=private,
                    timeout=8, banner_timeout=8, auth_timeout=8,
                    look_for_keys=False, allow_agent=False)
                result.update(authentication="PASS", host_trust="PINNED_KNOWN_HOSTS")
                code = Path(__file__).with_name("host_inventory.py").read_text()
                stdin, stdout, stderr = client.exec_command("python3 -", timeout=90)
                stdin.write(code)
                stdin.channel.shutdown_write()
                raw = stdout.read(65536)
                exit_code = stdout.channel.recv_exit_status()
                if exit_code:
                    result.update(status="BLOCKED_OS_INVENTORY", os_exit_code=exit_code)
                else:
                    inventory = json.loads(raw)
                    # Only known inventory fields; no arbitrary remote output.
                    result["os_inventory"] = {k: inventory[k] for k in
                        ("cpu_count", "loadavg", "memory", "disk_root", "container_runtime",
                         "docker_version", "compose_version", "containers", "volume_names") if k in inventory}
                    result["status"] = "PASS_READONLY_OS_INVENTORY"
    except Exception as exc:
        result["status"] = "BLOCKED_SSH_PROBE"
        result["error_class"] = type(exc).__name__
    finally:
        if transport:
            transport.close()
    return result


def main():
    report = {"project_id": PROJECT, "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": os.getenv("GITHUB_SHA"), "read_only": True,
        "secrets_present": {k: bool(os.getenv(k)) for k in PRESENCE},
        "vm_os_execution": "BLOCKED_UNVERIFIED_CHANNEL",
        "os_resources": "NOT_MEASURED", "deployment": "NOT_RUN",
        "llm": "NOT_TESTED", "llm_config_present": {k: bool(os.getenv(k)) for k in ("CLOUDRU_LLM_BASE_URL", "CLOUDRU_LLM_MODEL")}, "terraform_mutations": "NONE", "checks": {}}
    try:
        import boto3
        import requests
        from botocore.config import Config
        missing = [k for k in REQUIRED if not os.getenv(k)]
        if missing:
            raise ValueError("MISSING_REQUIRED_SECRET")
        sse = base64.b64decode(os.environ["CLOUDRU_STATE_SSE_CUSTOMER_KEY"].strip(), validate=True)
        if len(sse) != 32:
            raise ValueError("INVALID_SSE_KEY")
        access = os.getenv("CLOUDRU_STATE_ACCESS_KEY_ID", "")
        secret = os.getenv("CLOUDRU_STATE_SECRET_ACCESS_KEY", "")
        if bool(access) != bool(secret):
            raise ValueError("INCOMPLETE_S3_CREDENTIAL_PAIR")
        if not access:
            access = TENANT + ":" + os.environ["CLOUDRU_KEY_ID"]
            secret = os.environ["CLOUDRU_SECRET"]
        s3 = boto3.client("s3", endpoint_url="https://s3.cloud.ru", region_name="ru-central-1",
            aws_access_key_id=access, aws_secret_access_key=secret,
            config=Config(s3={"addressing_style": "path"}, connect_timeout=15, read_timeout=30,
                          retries={"max_attempts": 2}))
        body = s3.get_object(Bucket="test-bucket-ds", Key="terraform/p1/daniil-smirnov.tfstate",
            SSECustomerAlgorithm="AES256", SSECustomerKey=sse)["Body"]
        state = json.loads(body.read())
        selected = select_state(state)
        report["checks"]["existing_state_scope"] = "PASS"
        report["state_serial"] = state["serial"]
        key_body = None
        try:
            from cryptography.hazmat.primitives import serialization
            key_body = s3.get_object(Bucket="test-bucket-ds", Key="deployment/p1/ui-recovery-key.pem",
                SSECustomerAlgorithm="AES256", SSECustomerKey=sse)["Body"].read()
            recovery = serialization.load_ssh_private_key(key_body, password=None)
            public = recovery.public_key().public_bytes(serialization.Encoding.OpenSSH,
                serialization.PublicFormat.OpenSSH).decode()
            metadata = selected["ui"].get("image_metadata") or {}
            saved_public = (metadata.get("public_key") or {}).get("string_value", "")
            report["recovery_key"] = {"readable": True, "matches_ui_state_metadata":
                saved_public.split()[:2] == public.split()[:2], "os_authentication": "NOT_TESTED"}
            if not report["recovery_key"]["matches_ui_state_metadata"]:
                key_body = None
            del recovery, public
        except Exception as exc:
            key_body = None
            report["recovery_key"] = {"readable": False, "error_class": type(exc).__name__}

        response = requests.post("https://iam.api.cloud.ru/api/v1/auth/token",
            json={"keyId": os.environ["CLOUDRU_KEY_ID"], "secret": os.environ["CLOUDRU_SECRET"]}, timeout=30)
        response.raise_for_status()
        token = response.json()["access_token"]
        report["vms"] = {}
        for label in ("ui", "core"):
            expected = selected[label]
            response = requests.get("https://compute.api.cloud.ru/api/v1/vms/" + expected["id"],
                headers={"Authorization": "Bearer " + token}, timeout=30)
            response.raise_for_status()
            vm = response.json().get("vm", response.json())
            if vm.get("project", {}).get("id") != PROJECT or vm.get("name") != expected["name"]:
                raise ValueError("LIVE_VM_IDENTITY_MISMATCH")
            if live_zone_name(vm) != "ru.AZ-2":
                raise ValueError("LIVE_VM_ZONE_MISMATCH")
            if label == "ui" and not any(nic.get("id") == selected["ui_nic_id"]
                                          for nic in (vm.get("interfaces") or [])):
                raise ValueError("LIVE_UI_INTERFACE_MISMATCH")
            # Strictly allowlist status values; never publish arbitrary metadata.
            status = vm.get("state", "UNKNOWN")
            if not isinstance(status, str) or len(status) > 80:
                status = "UNKNOWN"
            report["vms"][label] = {"scope": "PASS", "state": status,
                "state_flavor": expected.get("flavor", {}).get("name"),
                "guest_agent_field_present": "guest_agent_state" in vm,
                "guest_agent_does_not_prove_exec": True}
        report["checks"]["ui_tcp_22"] = probe(selected["ui_ip"], 22)
        report["checks"]["ui_tcp_443"] = probe(selected["ui_ip"], 443)
        if report["checks"]["ui_tcp_22"] == "TCP_CONNECTED":
            report["ui_ssh"] = ssh_probe(selected["ui_ip"], key_body)
            if report["ui_ssh"]["status"] == "PASS_READONLY_OS_INVENTORY":
                report["vm_os_execution"] = "UI_READONLY_VERIFIED_CORE_UNVERIFIED"
                report["os_resources"] = "UI_MEASURED_CORE_NOT_MEASURED"
        del key_body
        report["inventory"] = "PASS"
    except Exception as exc:
        # Exception payloads may contain state or request credentials; class only.
        report["inventory"] = "BLOCKED"
        report["error_class"] = type(exc).__name__
        if isinstance(exc, ValueError) and str(exc) in {
            "PUBLIC_IP_INTERFACE_MISMATCH", "LIVE_UI_INTERFACE_MISMATCH",
            "STATE_IDENTITY_MISSING", "STATE_PROJECT_MISMATCH", "VM_IDENTITY_MISMATCH",
            "VM_ZONE_MISMATCH", "CORE_ID_MISMATCH", "PUBLIC_IP_ID_MISMATCH", "MISSING_REQUIRED_SECRET",
            "INVALID_SSE_KEY", "INCOMPLETE_S3_CREDENTIAL_PAIR", "LIVE_VM_IDENTITY_MISMATCH", "LIVE_VM_ZONE_MISMATCH"}:
            report["error_code"] = str(exc)
    target = Path(os.getenv("LAB_PREFLIGHT_REPORT", "lab-preflight.json"))
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["inventory"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
