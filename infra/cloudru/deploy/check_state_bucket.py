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


def validate(s3):
    bucket = os.environ["CLOUDRU_STATE_BUCKET"]
    assert len(bucket) >= 3 and len(bucket) <= 63 and bucket.isascii(), "invalid bucket name"
    # Enforce a project-bound bucket name as additional operator protection.
    assert bucket.startswith("dmrp-tfstate-daniil-"), "state bucket must use approved project prefix"
    s3.head_bucket(Bucket=bucket)
    versioning = s3.get_bucket_versioning(Bucket=bucket).get("Status")
    assert versioning == "Enabled", "bucket versioning is not enabled"
    tags = s3.get_bucket_tagging(Bucket=bucket).get("TagSet", [])
    project = {item.get("Key"): item.get("Value") for item in tags}.get(REQUIRED_TAG_KEY)
    assert project == EXPECTED, "bucket is not tagged for the approved Cloud.ru project"
    public = s3.get_public_access_block(Bucket=bucket).get("PublicAccessBlockConfiguration", {})
    required = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
    assert all(public.get(k) is True for k in required), "bucket is missing one or more public access restrictions"
    return {"project_id": EXPECTED, "bucket_name_validated": True,
            "versioning": "Enabled", "private": True,
            "tag_scope_verified": True, "lockfile_compatibility": "NOT_TESTED"}


def main():
    endpoint = os.getenv("CLOUDRU_STATE_S3_ENDPOINT") or "https://s3.cloud.ru"
    parsed = urlparse(endpoint)
    assert parsed.scheme == "https" and parsed.hostname and not parsed.username, "invalid HTTPS S3 endpoint"
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.getenv("CLOUDRU_STATE_REGION") or "ru-central-1",
        aws_access_key_id=os.environ["CLOUDRU_STATE_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CLOUDRU_STATE_SECRET_ACCESS_KEY"],
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
    )
    try:
        report = validate(s3)
        code = 0
    except Exception:
        # Error category intentionally does not disclose owner, bucket, endpoint,
        # credentials, or returned account resource metadata in a public repo.
        report = {"project_id": EXPECTED, "status": "FAIL",
                  "diagnostic": "Bucket existence, project tag, versioning, public block or credential permissions unverified."}
        code = 1
    with open(os.environ["CLOUDRU_STATE_REPORT"], "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return code


if __name__ == "__main__":
    sys.exit(main())
