"""Per-run records in the team bucket: runs/<run-id>/<stage>.json (spec section 4.1)."""

import json
import re

STAGES = ("ingest", "transform", "load")


def record_key(run_id: str, stage: str) -> str:
    if not re.fullmatch(r"[\w-]{1,80}", run_id):  # Step Functions execution names
        raise ValueError(f"bad run id: {run_id!r}")
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage!r}")
    return f"runs/{run_id}/{stage}.json"


def write(s3, bucket: str, run_id: str, stage: str, record: dict) -> str:
    key = record_key(run_id, stage)
    body = json.dumps(record, indent=2, sort_keys=True).encode()
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    return f"s3://{bucket}/{key}"


def read(s3, bucket: str, run_id: str, stage: str) -> dict:
    body = s3.get_object(Bucket=bucket, Key=record_key(run_id, stage))["Body"].read()
    return json.loads(body)
