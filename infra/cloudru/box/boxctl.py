"""Plan / apply / status / cleanup driver for the Cloud.ru service box.

The protected workflow ``.github/workflows/cloudru-box.yml`` calls these subcommands
between its Terraform steps. Each pure check lives in ``ownership.py``; this file
reads and writes files, runs Terraform and talks to the state bucket.

Nothing here prints secret values. Credentials come from the environment:

* ``TF_VAR_auth_key_id`` / ``TF_VAR_auth_secret``: Cloud.ru API key for the provider;
* ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``: S3 key for the state bucket;
* ``AWS_SSE_CUSTOMER_KEY``: base64 32-byte SSE-C key, also the plan digest HMAC key;
* ``CLOUDRU_STATE_BUCKET``: state bucket name.

Exit codes: 0 ok, 1 a check failed (reasons on stderr), 3 the box TTL has expired.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import ownership as own

ENDPOINT = "https://s3.cloud.ru"
REGION = "ru-central-1"
STATE_ROOT = "terraform/box/"
PROBE_ROOT = STATE_ROOT + "lock-probe-"
LOCK_ERROR = "Error acquiring the state lock"


def state_key(box_id: str) -> str:
    return f"{STATE_ROOT}{own.check_box_id(box_id)}.tfstate"


def ledger_key(box_id: str) -> str:
    return f"{STATE_ROOT}{own.check_box_id(box_id)}.ownership.json"


def backend_flags(bucket: str, key: str) -> list[str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket or ""):
        raise own.ScopeError("bucket name invalid")
    if not key.startswith(STATE_ROOT) or not key.endswith(".tfstate"):
        raise own.ScopeError("state key outside terraform/box/")
    return ["-backend-config=" + v for v in (
        "bucket=" + bucket, "key=" + key, "region=" + REGION, 'endpoints={s3="' + ENDPOINT + '"}',
        "use_lockfile=true", "encrypt=true", "skip_credentials_validation=true", "skip_region_validation=true",
        "skip_requesting_account_id=true", "skip_metadata_api_check=true", "use_path_style=true")]


# -- lock probe helpers (pure) ---------------------------------------------------------


def probe_prefix(run_id: str, attempt: str) -> str:
    if not (str(run_id).isdigit() and str(attempt).isdigit()):
        raise own.ScopeError("run id and attempt must be numeric")
    return f"{PROBE_ROOT}{run_id}-{attempt}"


def probe_keys(prefix: str) -> tuple[str, str]:
    if not prefix.startswith(PROBE_ROOT) or not re.fullmatch(r"\d+-\d+", prefix[len(PROBE_ROOT):]):
        raise own.ScopeError("not a lock probe prefix")
    return prefix + ".tfstate", prefix + ".tfstate.tflock"


def probe_versions_to_delete(listing: dict, prefix: str) -> list[tuple[str, str]]:
    """(key, version) pairs of exactly the two probe objects.

    ``list_object_versions(Prefix=...)`` also returns keys that merely start with the
    prefix (run 12 matches run 123), so every key is compared exactly.
    """
    keys = set(probe_keys(prefix))
    out = []
    for item in (listing.get("Versions") or []) + (listing.get("DeleteMarkers") or []):
        if item.get("Key") in keys and item.get("VersionId"):
            out.append((item["Key"], item["VersionId"]))
    return sorted(out)


# -- io helpers ------------------------------------------------------------------------


def read_json(path: str | None, *, missing_ok: bool = False):
    if not path:
        return None
    p = Path(path)
    if missing_ok and (not p.exists() or p.stat().st_size == 0):
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str, value) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=lambda o: o.__dict__) + "\n",
                          encoding="utf-8", newline="\n")


def digest_key() -> bytes:
    raw = os.environ.get("AWS_SSE_CUSTOMER_KEY", "").strip()
    try:
        key = base64.b64decode(raw, validate=True)
    except ValueError:
        key = b""
    if len(key) != 32:
        raise own.ScopeError("AWS_SSE_CUSTOMER_KEY must be a base64 32-byte key")
    return key


def s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION,
                        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
                        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}))


def sse_args() -> dict:
    return {"SSECustomerAlgorithm": "AES256", "SSECustomerKey": digest_key()}


def fail(problems: list[str]) -> int:
    for p in problems:
        print("problem: " + p, file=sys.stderr)
    return 1


def terraform(args: list[str], cwd: Path, env=None, check=True, timeout=900) -> subprocess.CompletedProcess:
    p = subprocess.run(["terraform", *args], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=timeout)
    if check and p.returncode:
        # Terraform redacts sensitive variables in its own errors; the first lines name the failing step.
        tail = [line for line in p.stdout.splitlines() if line.startswith(("Error", "│ Error"))][:5]
        raise SystemExit(f"terraform {args[0]} failed: " + " | ".join(tail))
    return p


# -- subcommands -----------------------------------------------------------------------


def cmd_init(a) -> int:
    flags = backend_flags(os.environ["CLOUDRU_STATE_BUCKET"], state_key(a.box_id))
    terraform(["init", "-reconfigure", "-input=false", "-no-color", *flags], Path(a.dir))
    print("backend initialized: key " + state_key(a.box_id) + ", use_lockfile=true, SSE-C")
    return 0


def cmd_classify(a) -> int:
    live, meta = own.live_inventory(read_json(a.inventory))
    state = own.state_records(read_json(a.state, missing_ok=True))
    report = own.classify(live, state, a.box_id)
    adopted = {tuple(x.strip().split("=", 1)) for x in (a.adopt or "").split(",") if "=" in x}
    # An orphan the owner chose to adopt is imported by this plan instead of blocking it.
    problems = [p for p in report["problems"]
                if not (p.startswith("orphan:") and tuple(p.split(":", 2)[1:]) in adopted)]
    if a.subnet not in meta["subnet_ids"]:
        problems.append("approved_subnet_not_in_project")
    # A first apply needs one more public IP and 2 vCPU, unless it imports the orphan that already uses them.
    adopted_kinds = {kind for kind, _ in adopted}
    need = {} if state else {code: n for code, n, kind in (("network.ip.quantity", 1, "external_ip"),
                                                           ("compute.vcpu", 2, "vm")) if kind not in adopted_kinds}
    problems += own.quota_problems(meta["quotas"], need)
    out = {"box_id": a.box_id, "owned": report["owned"], "orphans": report["orphans"],
           "duplicates": report["duplicates"], "missing_outside_terraform": report["missing"],
           "foreign_counts": report["foreign"], "problems": problems}
    if a.out:
        write_json(a.out, out)
    print(f"owned {len(report['owned'])}, orphans {len(report['orphans'])}, duplicates {len(report['duplicates'])}, "
          f"missing {len(report['missing'])}, foreign {report['foreign']}")
    return fail(problems) if problems else 0


def cmd_recover(a) -> int:
    for address in own.untaint_candidates(own.state_records(read_json(a.state, missing_ok=True)), a.box_id):
        print(address)
    return 0


def cmd_adopt(a) -> int:
    live, _ = own.live_inventory(read_json(a.inventory))
    report = own.classify(live, own.state_records(read_json(a.state, missing_ok=True)), a.box_id)
    blocks = []
    for item in filter(None, (a.adopt or "").split(",")):
        kind, _, rid = item.strip().partition("=")
        blocks.append(own.adopt_block(report, kind, rid))
    Path(a.out).write_text("".join(blocks), encoding="utf-8", newline="\n")
    print(f"import blocks: {len(blocks)}")
    return 0


def cmd_guard(a) -> int:
    plan = read_json(a.plan)
    state = own.state_records(read_json(a.state, missing_ok=True))
    adopt_ids = [x.partition("=")[2] for x in filter(None, (a.adopt or "").split(","))]
    problems = own.guard_plan(plan, a.mode, a.box_id, state, adopt_ids=adopt_ids)
    if a.mode == "apply":
        problems += own.check_ttl(a.expires_on, dt.date.fromisoformat(a.today) if a.today else dt.date.today())
    projection = own.plan_projection(plan, key=digest_key(), commit=a.commit, box_id=a.box_id, mode=a.mode)
    value = own.digest(projection)
    write_json(a.projection, projection)
    counts: dict[str, int] = {}
    for c in projection["changes"]:
        counts["-".join(c["actions"])] = counts.get("-".join(c["actions"]), 0) + 1
    print(f"plan digest {value}; actions {counts}")
    if a.expect_digest and a.expect_digest != value:
        problems.append("plan_digest_differs_from_reviewed")
    return fail(problems) if problems else 0


def cmd_status(a) -> int:
    raw = read_json(a.state, missing_ok=True)
    state = own.state_records(raw)
    live, _ = own.live_inventory(read_json(a.inventory))
    report = own.classify(live, state, a.box_id)
    expires = ((raw or {}).get("outputs", {}).get("ownership", {}).get("value") or {}).get("expires_on")
    ttl = own.ttl_state(expires, dt.date.fromisoformat(a.today) if a.today else dt.date.today()) if expires else None
    out = {"box_id": a.box_id, "resources": [{"address": r.address, "name": r.name, "tainted": r.tainted} for r in state],
           "live": [{"kind": x.kind, "name": x.name, "status": x.status} for x in report["owned"]],
           "missing_outside_terraform": [r.address for r in report["missing"]],
           "orphans": [x.__dict__ for x in report["orphans"]], "ttl": ttl, "problems": report["problems"]}
    if a.out:
        write_json(a.out, out)
    print(json.dumps({k: out[k] for k in ("box_id", "ttl", "problems")}, ensure_ascii=False))
    for r in out["resources"]:
        print(f"  {r['address']}  {r['name']}{'  TAINTED' if r['tainted'] else ''}")
    if ttl and ttl["expired"]:
        print("EXPIRED: run operation destroy-plan, review it, then destroy", file=sys.stderr)
        return 3
    return 0


def cmd_cleanup_check(a) -> int:
    live, _ = own.live_inventory(read_json(a.inventory))
    result = own.cleanup_selection(read_json(a.plan), own.state_records(read_json(a.state, missing_ok=True)),
                                   read_json(a.ledger, missing_ok=True), live, a.box_id)
    if a.out:
        write_json(a.out, result)
    print(f"delete {len(result['delete'])}; left in place: orphans {len(result['left_in_place']['orphans'])}, "
          f"foreign {result['left_in_place']['foreign']}")
    return fail(result["problems"]) if result["problems"] else 0


def cmd_ledger_put(a) -> int:
    raw = read_json(a.state, missing_ok=True)
    ledger = own.ledger_from_state(own.state_records(raw), box_id=a.box_id, expires_on=a.expires_on,
                                   commit=a.commit, plan_digest=a.digest)
    body = json.dumps(ledger, indent=2, sort_keys=True).encode()
    s3_client().put_object(Bucket=os.environ["CLOUDRU_STATE_BUCKET"], Key=ledger_key(a.box_id), Body=body,
                           ContentType="application/json", **sse_args())
    print(f"ledger written: {len(ledger['resources'])} resources")
    return 0


def cmd_ledger_get(a) -> int:
    from botocore.exceptions import ClientError

    try:
        obj = s3_client().get_object(Bucket=os.environ["CLOUDRU_STATE_BUCKET"], Key=ledger_key(a.box_id), **sse_args())
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            Path(a.out).write_text("", encoding="utf-8")
            print("ledger absent")
            return 0
        raise SystemExit("ledger read failed: " + exc.response.get("Error", {}).get("Code", "REQUEST_FAILED")) from None
    Path(a.out).write_bytes(obj["Body"].read())
    print("ledger read")
    return 0


PROBE_TF = """terraform {
  backend "s3" {}
}
variable "sleep_seconds" {
  type    = number
  default = 25
}
resource "terraform_data" "probe" {
  input = "box state lock probe; no cloud resources"
  provisioner "local-exec" {
    command = "sleep ${var.sleep_seconds}"
  }
}
"""


def cmd_lock_test(a) -> int:
    """Prove locking, SSE-C and recovery on the real bucket under terraform/box/lock-probe-*.

    Creates only two probe objects (state and lock) and deletes exactly their versions.
    Writes a PASS/FAIL report; never touches terraform/box/<box_id>.tfstate.
    """
    bucket = os.environ["CLOUDRU_STATE_BUCKET"]
    prefix = probe_prefix(os.environ["GITHUB_RUN_ID"], os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    state_obj, lock_obj = probe_keys(prefix)
    flags = backend_flags(bucket, state_obj)
    s3 = s3_client()
    sse = sse_args()
    env = dict(os.environ, TF_IN_AUTOMATION="true")
    checks: dict[str, str] = {}

    def wait_lock(seconds=30):
        for _ in range(seconds):
            try:
                s3.head_object(Bucket=bucket, Key=lock_obj, **sse)
                return True
            except Exception:
                time.sleep(1)
        return False

    def competitor(directory):
        p = terraform(["plan", "-input=false", "-no-color", "-lock-timeout=2s"], directory, env, check=False)
        return p.returncode != 0 and LOCK_ERROR in p.stdout

    root = Path(tempfile.mkdtemp(prefix="box-lock-"))
    try:
        writer, reader = root / "writer", root / "reader"
        for d in (writer, reader):
            d.mkdir()
            (d / "main.tf").write_text(PROBE_TF, encoding="utf-8")
            terraform(["init", "-input=false", "-no-color", *flags], d, env)
        # 1. a running apply holds an SSE-C encrypted lock object; a second client is rejected
        with open(root / "writer.log", "w") as log:
            proc = subprocess.Popen(["terraform", "apply", "-auto-approve", "-input=false", "-no-color"],
                                    cwd=writer, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                checks["lock_object_encrypted"] = "PASS" if wait_lock() else "FAIL"
                checks["concurrent_run_rejected"] = "PASS" if competitor(reader) else "FAIL"
                checks["writer_finished"] = "PASS" if proc.wait(timeout=120) == 0 else "FAIL"
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        # 2. state is SSE-C encrypted, unreadable without the key, and a fresh client sees it
        head = s3.head_object(Bucket=bucket, Key=state_obj, **sse)
        checks["state_encrypted"] = "PASS" if head.get("SSECustomerAlgorithm") == "AES256" else "FAIL"
        try:
            s3.get_object(Bucket=bucket, Key=state_obj)
            checks["state_unreadable_without_key"] = "FAIL"
        except Exception:
            checks["state_unreadable_without_key"] = "PASS"
        pulled = json.loads(terraform(["state", "pull"], reader, env).stdout)
        checks["fresh_client_reads_state"] = "PASS" if [r["type"] for r in pulled.get("resources", [])] == ["terraform_data"] else "FAIL"
        noop = terraform(["plan", "-input=false", "-no-color", "-detailed-exitcode"], reader, env, check=False)
        checks["rerun_is_noop"] = "PASS" if noop.returncode == 0 else "FAIL"
        # 3. a killed apply leaves its lock; it still blocks; force-unlock by its exact ID recovers
        with open(root / "killed.log", "w") as log:
            proc = subprocess.Popen(["terraform", "apply", "-auto-approve", "-input=false", "-no-color",
                                     "-replace=terraform_data.probe", "-var=sleep_seconds=60"],
                                    cwd=writer, env=env, stdout=log, stderr=subprocess.STDOUT)
            seen = wait_lock()
            proc.kill()
            proc.wait()
        checks["killed_run_leaves_lock"] = "PASS" if seen and wait_lock(3) else "FAIL"
        checks["stale_lock_still_blocks"] = "PASS" if competitor(reader) else "FAIL"
        lock_id = json.loads(s3.get_object(Bucket=bucket, Key=lock_obj, **sse)["Body"].read()).get("ID", "")
        unlock = terraform(["force-unlock", "-force", lock_id], reader, env, check=False) if lock_id else None
        after = terraform(["plan", "-input=false", "-no-color", "-lock-timeout=2s"], reader, env, check=False)
        checks["force_unlock_by_id_recovers"] = "PASS" if unlock and unlock.returncode == 0 and after.returncode == 0 else "FAIL"
    finally:
        listing = s3.list_object_versions(Bucket=bucket, Prefix=prefix)
        for key, version in probe_versions_to_delete(listing, prefix):
            s3.delete_object(Bucket=bucket, Key=key, VersionId=version)
        shutil.rmtree(root, ignore_errors=True)
    status = "PASS" if checks and all(v == "PASS" for v in checks.values()) else "FAIL"
    write_json(a.out, {"status": status, "prefix": prefix, "checks": checks,
                       "production_state_touched": False, "cloud_resources_created": 0})
    print(json.dumps({"status": status, "checks": checks}))
    return 0 if status == "PASS" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, func, *args):
        p = sub.add_parser(name)
        p.set_defaults(func=func)
        p.add_argument("--box-id", required=True)
        for arg in args:
            p.add_argument("--" + arg, required=arg not in ("state", "out", "expect-digest", "adopt", "today",
                                                             "ledger", "expires-on"))
        return p

    command("init", cmd_init, "dir")
    command("classify", cmd_classify, "inventory", "state", "subnet", "adopt", "out")
    command("recover", cmd_recover, "state")
    command("adopt", cmd_adopt, "inventory", "state", "adopt", "out")
    g = command("guard", cmd_guard, "plan", "state", "commit", "projection", "expect-digest", "adopt",
                "expires-on", "today")
    g.add_argument("--mode", choices=["apply", "destroy"], required=True)
    command("status", cmd_status, "inventory", "state", "today", "out")
    command("cleanup-check", cmd_cleanup_check, "plan", "state", "ledger", "inventory", "out")
    command("ledger-put", cmd_ledger_put, "state", "expires-on", "commit", "digest")
    command("ledger-get", cmd_ledger_get, "out")
    command("lock-test", cmd_lock_test, "out")
    a = parser.parse_args(argv)
    try:
        return a.func(a)
    except own.ScopeError as exc:
        return fail([str(exc)])


if __name__ == "__main__":
    raise SystemExit(main())
