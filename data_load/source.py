"""Fingerprint the organizer's source files so a later re-upload is detectable."""

import hashlib

from data_load.stage import EVENT_TABLES


def source_prefix(prefix: str, table: str) -> str:
    """S3 key prefix of one table's source files; `table` may be schema-qualified."""
    name = table.split(".")[-1]
    base = prefix.rstrip("/") + "/" if prefix.strip("/") else ""
    return f"{base}{name}/" if name in EVENT_TABLES else f"{base}{name}.csv"


def list_objects(s3, bucket: str, key_prefix: str) -> list[tuple[str, str]]:
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        objects += [(o["Key"], o["ETag"].strip('"')) for o in page.get("Contents", [])]
    return objects


def etag_digest(objects: list[tuple[str, str]]) -> str:
    """SHA-256 over sorted 'key etag' lines: any added, removed or rewritten file changes it."""
    lines = "\n".join(f"{key} {etag}" for key, etag in sorted(objects))
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
