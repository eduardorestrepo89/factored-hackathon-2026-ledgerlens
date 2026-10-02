"""Stage 1: copy the organizer's CSVs into raw/<run-id>/ and record their ETags (spec 4.1).

The organizer's keys are fetched from Secrets Manager here and nowhere else; they never
sit in an environment variable, a file, the run record or a log (spec section 12).
"""

import json
from concurrent.futures import ThreadPoolExecutor

from data_load.source import etag_digest, list_objects, normalize_prefix, source_prefix

SECRET_KEYS = (
    "aws_access_key_id",
    "aws_secret_access_key",
    "bucket",
    "region",
    "prefix",
)


class IngestError(RuntimeError):
    """A table has no files, a copy came up short, or the secret is malformed.
    Messages name keys and files, never secret values."""


def parse_secret(raw: str) -> dict:
    try:
        secret = json.loads(raw)
    except json.JSONDecodeError:
        raise IngestError("the organizer secret is not valid JSON") from None
    if not isinstance(secret, dict):
        raise IngestError("the organizer secret must be a JSON object")
    missing = [key for key in SECRET_KEYS if not secret.get(key)]
    if missing:
        raise IngestError(f"the organizer secret is missing: {', '.join(missing)}")
    return secret


def load_secret(secrets, secret_id: str) -> dict:
    return parse_secret(secrets.get_secret_value(SecretId=secret_id)["SecretString"])


def raw_key(run_id: str, prefix: str, key: str) -> str:
    """data/transactions/year=2024/.../x.csv -> raw/<run-id>/transactions/year=2024/.../x.csv"""
    return f"raw/{run_id}/{key[len(normalize_prefix(prefix)) :]}"


def ingest(
    org_s3,
    team_s3,
    secret: dict,
    team_bucket: str,
    run_id: str,
    tables: list[str],
    workers: int = 16,
) -> dict:
    """Copy every source file byte for byte; return the ingest record."""
    bucket, prefix = secret["bucket"], secret["prefix"]
    listed = {t: list_objects(org_s3, bucket, source_prefix(prefix, t)) for t in tables}
    empty = [t for t, objects in listed.items() if not objects]
    if empty:  # usually a wrong bucket or prefix in the secret
        raise IngestError(f"no source files: {', '.join(empty)}")

    def copy(obj: tuple[str, str, int]) -> str | None:
        key, _etag, size = obj
        dest = raw_key(run_id, prefix, key)
        body = org_s3.get_object(Bucket=bucket, Key=key)["Body"]
        team_s3.upload_fileobj(body, team_bucket, dest)
        copied = team_s3.head_object(Bucket=team_bucket, Key=dest)["ContentLength"]
        return None if copied == size else f"{key} ({copied:,} of {size:,} bytes)"

    everything = [obj for objects in listed.values() for obj in objects]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        short = [s for s in pool.map(copy, everything) if s]
    if short:
        raise IngestError(
            f"{len(short)} incomplete copies, e.g. {', '.join(short[:5])}"
        )
    return {
        "run_id": run_id,
        "source": {"bucket": bucket, "prefix": prefix, "region": secret["region"]},
        "raw_prefix": f"s3://{team_bucket}/raw/{run_id}/",
        "tables": {
            table: {
                "files": len(objects),
                "bytes": sum(size for _, _, size in objects),
                "etag_digest": etag_digest(objects),
                "objects": [list(obj) for obj in objects],
            }
            for table, objects in listed.items()
        },
    }
