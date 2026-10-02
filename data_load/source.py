"""List the organizer's source files and fingerprint them, so a re-upload is detectable."""

import hashlib

EVENT_TABLES = frozenset(
    {
        "call_center_interactions",
        "call_transcripts",
        "campaign_sends",
        "complaints",
        "digital_events",
        "satisfaction_surveys",
        "transactions",
    }
)


def normalize_prefix(prefix: str) -> str:
    """'data', 'data/' and '/data/' all become 'data/'; an empty prefix stays empty."""
    return prefix.strip("/") + "/" if prefix.strip("/") else ""


def source_prefix(prefix: str, table: str) -> str:
    """S3 key prefix of one table's source files."""
    base = normalize_prefix(prefix)
    return f"{base}{table}/" if table in EVENT_TABLES else f"{base}{table}.csv"


def list_objects(s3, bucket: str, key_prefix: str) -> list[tuple[str, str, int]]:
    """(key, etag, size) of every object under key_prefix."""
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        objects += [
            (o["Key"], o["ETag"].strip('"'), o["Size"])
            for o in page.get("Contents", [])
        ]
    return objects


def etag_digest(objects: list[tuple[str, str, int]]) -> str:
    """SHA-256 over sorted 'key etag' lines: any added, removed or rewritten file changes it."""
    lines = "\n".join(f"{key} {etag}" for key, etag, *_ in sorted(objects))
    return hashlib.sha256(lines.encode()).hexdigest()


def fingerprint(
    s3, bucket: str, prefix: str, tables: list[str]
) -> dict[str, tuple[int, str]]:
    """table -> (number of source files, ETag digest)."""
    result = {}
    for table in tables:
        objects = list_objects(s3, bucket, source_prefix(prefix, table))
        result[table] = (len(objects), etag_digest(objects))
    return result


def drift(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    """Tables whose digest differs, or that exist on only one side."""
    tables = recorded.keys() | current.keys()
    return sorted(t for t in tables if recorded.get(t) != current.get(t))
