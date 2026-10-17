"""Read-only validation of dedicated Terraform state object storage.

Never sends secrets to stdout; never creates, deletes or updates objects/buckets.
Does not prove Terraform lock-file compatibility; only actual protected
init/plan can test that after the owner grants credentials.
"""
from __future__ import annotations
import ipaddress
import json
import os
import sys
from urllib.parse import urlparse

EXPECTED = "20853297-65b7-42a8-af40-25c8d2df4e11"
REQUIRED_TAG_KEY = "cloudru_project_id"


def read_setting(s3, method, bucket):
    try:
        return getattr(s3, method)(Bucket=bucket)
    except Exception as error:
        response = getattr(error, "response", {})
        error_code = response.get("Error", {}).get("Code", "")
        allowed = {"NoSuchTagSet", "AccessDenied", "NoSuchBucket", "NoSuchPublicAccessBlockConfiguration", "NotImplemented"}
        safe_code = error_code if error_code in allowed else "REQUEST_FAILED"
        raise AssertionError(method + ": " + safe_code) from None


def validate(s3):
    bucket = os.environ["CLOUDRU_STATE_BUCKET"]
    assert len(bucket) >= 3 and len(bucket) <= 63 and bucket.isascii(), "invalid bucket name"
    # Enforce a project-bound bucket name as additional operator protection.
    assert bucket.startswith("dmrp-tfstate-daniil-") or bucket == "test-bucket-ds", "state bucket is outside the approved scope"
    s3.head_bucket(Bucket=bucket)
    versioning = read_setting(s3, "get_bucket_versioning", bucket).get("Status")
    assert versioning == "Enabled", "bucket versioning is not enabled"
    tags = read_setting(s3, "get_bucket_tagging", bucket).get("TagSet", [])
    project = {item.get("Key"): item.get("Value") for item in tags}.get(REQUIRED_TAG_KEY)
    assert project == EXPECTED, "bucket is not tagged for the approved Cloud.ru project"
    public = read_setting(s3, "get_public_access_block", bucket).get("PublicAccessBlockConfiguration", {})
    required = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
    assert all(public.get(k) is True for k in required), "bucket is missing one or more public access restrictions"
    return {"project_id": EXPECTED, "bucket_name_validated": True,
            "versioning": "Enabled", "private": True,
            "tag_scope_verified": True, "lockfile_compatibility": "NOT_TESTED"}


def main():
    endpoint = os.getenv("CLOUDRU_STATE_S3_ENDPOINT") or "https://s3.cloud.ru"
    parsed = urlparse(endpoint)
    assert parsed.scheme == "https" and parsed.hostname and not parsed.username, "invalid HTTPS S3 endpoint"
    access_key = os.getenv("CLOUDRU_STATE_ACCESS_KEY_ID")
    secret_key = os.getenv("CLOUDRU_STATE_SECRET_ACCESS_KEY")
    if not access_key and not secret_key:
        # Read-only diagnostic reuse only. Protected apply still requires
        # separately configured state credentials.
        tenant = os.getenv("CLOUDRU_TENANT_ID")
        assert tenant == "fc91c42d-c2ea-4d6d-a236-103fd1f37f00", "unexpected tenant"
        assert os.getenv("CLOUDRU_STATE_BUCKET") == "test-bucket-ds", "unexpected bucket"
        key_id = os.environ["CLOUDRU_KEY_ID"]
        access_key = tenant + ":" + key_id
        secret_key = os.environ["CLOUDRU_SECRET"]
        # GitHub's original key mask does not cover the composed S3 ID.
        print("::add-mask::" + access_key)
    assert access_key and secret_key, "incomplete state credentials"
    assert endpoint == "https://s3.cloud.ru", "unexpected S3 destination"
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.getenv("CLOUDRU_STATE_REGION") or "ru-central-1",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
    )
    authenticated = False
    try:
        s3.head_bucket(Bucket=os.environ["CLOUDRU_STATE_BUCKET"])
        authenticated = True
        report = validate(s3)
        code = 0
    except AssertionError as error:
        # These messages are our fixed validation labels, never provider bodies.
        report = {"project_id": EXPECTED, "status": "FAIL",
                  "bucket_read_access": authenticated, "diagnostic": str(error)}
        code = 1
    except Exception:
        # Error category intentionally does not disclose owner, bucket, endpoint,
        # credentials, or returned account resource metadata in a public repo.
        report = {"project_id": EXPECTED, "status": "FAIL", "bucket_read_access": authenticated,
                  "diagnostic": "Bucket existence, project tag, versioning, public block or credential permissions unverified."}
        code = 1
    with open(os.environ["CLOUDRU_STATE_REPORT"], "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return code


if __name__ == "__main__":
    sys.exit(main())
