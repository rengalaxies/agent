"""Read only the existing approved state and exact VMs; emit an allowlisted report.

No Terraform init/apply, VM actions, broad project inventory or remote execution.
State and API responses remain in memory, never in logs or artifacts.
"""
import base64
import json
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
    "CLOUDRU_LAB_SSH_PRIVATE_KEY", "CLOUDRU_LAB_SSH_KNOWN_HOSTS", "CLOUDRU_LLM_API_KEY"]


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
        if vm.get("zone", {}).get("name") != "ru.AZ-2":
            raise ValueError("VM_ZONE_MISMATCH")
        result[label] = vm
    if result["core"]["id"] != "97a6e631-1d80-4212-aa69-ef6454b029df":
        raise ValueError("CORE_ID_MISMATCH")
    ip = managed[("cloudru_evolution_compute_external_ip", "ui", None)]
    if ip.get("id") != "33a27f64-e474-49ed-a17b-15f67dd16400":
        raise ValueError("PUBLIC_IP_ID_MISMATCH")
    result["ui_ip"] = ip["ip_address"]
    return result


def probe(host, port):
    try:
        with socket.create_connection((host, port), timeout=6):
            return "TCP_CONNECTED"
    except OSError:
        return "TCP_UNREACHABLE"


def main():
    report = {"project_id": PROJECT, "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": os.getenv("GITHUB_SHA"), "read_only": True,
        "secrets_present": {k: bool(os.getenv(k)) for k in PRESENCE},
        "vm_os_execution": "BLOCKED_UNVERIFIED_CHANNEL",
        "os_resources": "NOT_MEASURED", "deployment": "NOT_RUN",
        "llm": "NOT_TESTED", "llm_config_present": {k: bool(os.getenv(k)) for k in ("LAB_LLM_BASE_URL", "LAB_LLM_MODEL")}, "terraform_mutations": "NONE", "checks": {}}
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
            del key_body, recovery, public
        except Exception as exc:
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
            if vm.get("zone", {}).get("name") != "ru.AZ-2":
                raise ValueError("LIVE_VM_ZONE_MISMATCH")
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
        report["inventory"] = "PASS"
    except Exception as exc:
        # Exception payloads may contain state or request credentials; class only.
        report["inventory"] = "BLOCKED"
        report["error_class"] = type(exc).__name__
        if isinstance(exc, ValueError) and str(exc) in {
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
