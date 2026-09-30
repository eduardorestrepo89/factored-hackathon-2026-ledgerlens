"""python -m data_load {stage,run,check}.

Design: docs/superpowers/specs/2026-09-29-data-loading-design.md
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from data_load.ddl import load_plan
from data_load.stage import load_window, stage

CONFIG = Path(__file__).resolve().parents[1] / "infra-cdk" / "config.yaml"
SECRET_KEYS = (
    "aws_access_key_id",
    "aws_secret_access_key",
    "bucket",
    "region",
    "prefix",
)
RUN_ENV = ("AS_OF", "WINDOW_YEARS", "DSQL_ENDPOINT", "TEAM_BUCKET", "HACKATHON_S3")


def config_defaults() -> dict:
    """The `data:` block of infra-cdk/config.yaml, when running from a repo checkout."""
    if not CONFIG.exists():
        return {}
    return (yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}).get("data") or {}


def parse_hackathon_secret(raw: str) -> dict:
    """Parse HACKATHON_S3. Errors name missing keys and never echo values."""
    try:
        secret = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit("HACKATHON_S3 is not valid JSON") from None
    if not isinstance(secret, dict):
        raise SystemExit("HACKATHON_S3 must be a JSON object")
    missing = [key for key in SECRET_KEYS if not secret.get(key)]
    if missing:
        raise SystemExit(f"HACKATHON_S3 is missing: {', '.join(missing)}")
    return secret


def cmd_stage(args) -> int:
    if args.as_of is None or args.window_years is None:
        raise SystemExit(
            "--as-of and --window-years are required (no data block in config.yaml)"
        )
    tables = args.tables.split(",") if args.tables else None
    staged = stage(
        args.source, Path(args.out), args.as_of, args.window_years, tables=tables
    )
    print(f"total {sum(s.rows for s in staged):,} rows in {len(staged)} tables")
    return 0


def cmd_run(args) -> int:
    missing = [name for name in RUN_ENV if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"missing environment variables: {', '.join(missing)}")
    import boto3

    from data_load import dsql, source

    secret = parse_hackathon_secret(os.environ["HACKATHON_S3"])
    as_of = datetime.fromisoformat(os.environ["AS_OF"])
    years = int(os.environ["WINDOW_YEARS"])
    endpoint, team_bucket = os.environ["DSQL_ENDPOINT"], os.environ["TEAM_BUCKET"]
    plan = load_plan()

    # 1. Stage from the hackathon bucket; nothing in AWS is written yet
    origin = f"s3://{secret['bucket']}/{secret['prefix']}"
    staged = stage(origin, Path(args.out), as_of, years, s3=secret, plan=plan)
    org_s3 = boto3.client(
        "s3",
        region_name=secret["region"],
        aws_access_key_id=secret["aws_access_key_id"],
        aws_secret_access_key=secret["aws_secret_access_key"],
    )
    prints = source.fingerprint(
        org_s3, secret["bucket"], secret["prefix"], [s.table for s in staged]
    )

    # 2. Upload, largest first so the longest load starts first
    team_s3 = boto3.client("s3")
    key_base = f"staging/{as_of:%Y%m%dT%H%M%S}"
    uris = {}
    for s in sorted(staged, key=lambda s: s.rows, reverse=True):
        key = f"{key_base}/{s.path.name}"
        team_s3.upload_file(str(s.path), team_bucket, key)
        team_s3.put_object(
            Bucket=team_bucket, Key=f"{key}.sha256", Body=s.sha256.encode()
        )
        uris[s.table] = f"s3://{team_bucket}/{key}"

    # 3. Schema, roles, grants. A DSQL connection lives at most 60 min: reconnect after the load.
    conn = dsql.connect(endpoint)
    try:
        dsql.apply_schema(conn, plan)
    finally:
        conn.close()

    # 4. Bulk load
    dsql.load_all(endpoint, uris)

    # 5-6. Indexes, then verify counts and record lineage
    start, end = load_window(as_of, years)
    rows = [
        dsql.ManifestRow(
            table_name=s.table,
            as_of=as_of,
            window_start=start,
            window_end=end,
            source_uri=f"s3://{secret['bucket']}/{source.source_prefix(secret['prefix'], s.table)}",
            source_files=prints[s.table][0],
            source_etag_digest=prints[s.table][1],
            staged_uri=uris[s.table],
            staged_sha256=s.sha256,
            rows_staged=s.rows,
        )
        for s in staged
    ]
    conn = dsql.connect(endpoint)
    try:
        dsql.build_indexes(conn, plan.data_indexes)
        dsql.record_manifest(conn, rows)
    finally:
        conn.close()
    print(
        f"data_load: done, {sum(s.rows for s in staged):,} rows in {len(staged)} tables",
        flush=True,
    )
    return 0


def cmd_check(args) -> int:
    import boto3

    from data_load import dsql, source

    conn = dsql.connect(args.endpoint, profile=args.dsql_profile)
    try:
        recorded = dsql.recorded_digests(conn)
    finally:
        conn.close()
    if not recorded:
        print("no load recorded in app.load_manifest")
        return 1
    org_s3 = boto3.Session(profile_name=args.bucket_profile).client(
        "s3", region_name=args.region
    )
    prints = source.fingerprint(org_s3, args.bucket, args.prefix, list(recorded))
    changed = source.drift(recorded, {t: digest for t, (_, digest) in prints.items()})
    if changed:
        print("changed since the last load: " + ", ".join(changed))
        return 1
    print("no drift: the bucket matches the last load")
    return 0


def main(argv: list[str] | None = None) -> int:
    defaults = config_defaults()
    parser = argparse.ArgumentParser(prog="python -m data_load")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "stage", help="validate CSVs and write Parquet locally (no AWS writes)"
    )
    p.add_argument(
        "--source",
        required=True,
        help="directory or s3:// URI in the organizer data/ layout",
    )
    p.add_argument("--out", required=True)
    p.add_argument(
        "--as-of", type=datetime.fromisoformat, default=defaults.get("as_of")
    )
    p.add_argument("--window-years", type=int, default=defaults.get("window_years"))
    p.add_argument("--tables", help="comma-separated subset, e.g. bank.transactions")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser(
        "run", help="stage from the hackathon bucket and load Aurora DSQL (CodeBuild)"
    )
    p.add_argument(
        "--out", default=str(Path(tempfile.gettempdir()) / "ledgerlens-stage")
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser(
        "check", help="compare the bucket's ETags with app.load_manifest"
    )
    p.add_argument("--bucket", required=True)
    p.add_argument("--endpoint", required=True, help="stack output DsqlEndpoint")
    p.add_argument("--prefix", default="data/")
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--bucket-profile", default="hackathon")
    p.add_argument("--dsql-profile", default="ledgerlens")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
