"""python -m data_load {ingest,transform,curate,load,access,check}: the data pipeline's stages.

CodeBuild runs `python -m data_load $STAGE` for stages 1-4; Step Functions sets STAGE
and RUN_ID. Design: docs/superpowers/specs/2026-10-02-data-pipeline-design.md and
docs/superpowers/specs/2026-10-03-curate-stage-design.md
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from data_load.ddl import load_plan

WORK = Path(tempfile.gettempdir()) / "ledgerlens-pipeline"


def require_env(*names: str) -> list[str]:
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"missing environment variables: {', '.join(missing)}")
    return [os.environ[name] for name in names]


def cmd_ingest(args) -> int:
    run_id, bucket, secret_id = require_env(
        "RUN_ID", "TEAM_BUCKET", "HACKATHON_SECRET_ID"
    )
    import boto3

    from data_load import ingest, runrecord

    team_s3 = boto3.client("s3")
    runrecord.clear(team_s3, bucket, run_id, "ingest")
    secret = ingest.load_secret(boto3.client("secretsmanager"), secret_id)
    org_s3 = boto3.client(
        "s3",
        region_name=secret["region"],
        aws_access_key_id=secret["aws_access_key_id"],
        aws_secret_access_key=secret["aws_secret_access_key"],
    )
    tables = list(load_plan().data_tables)
    record = ingest.ingest(org_s3, team_s3, secret, bucket, run_id, tables)
    uri = runrecord.write(team_s3, bucket, run_id, "ingest", record)
    files = sum(t["files"] for t in record["tables"].values())
    print(
        f"ingest: {files:,} files copied to {record['raw_prefix']}, record {uri}",
        flush=True,
    )
    return 0


def cmd_transform(args) -> int:
    from data_load.transform import download_raw, load_expected, transform

    if args.tables and not args.source:
        raise SystemExit("--tables is only for local runs with --source")
    tables = args.tables.split(",") if args.tables else None
    expected = None if tables else load_expected()
    if args.source:  # local rehearsal: nothing in AWS is read or written
        written, counts = transform(
            args.source, Path(args.out), tables=tables, expected=expected
        )
        print(f"total {sum(t.rows for t in written):,} rows in {len(written)} tables")
        print(f"repairs {counts}")
        return 0

    run_id, bucket = require_env("RUN_ID", "TEAM_BUCKET")
    import boto3

    from data_load import runrecord

    s3 = boto3.client("s3")
    runrecord.clear(s3, bucket, run_id, "transform")
    raw = Path(args.out) / "raw"
    shutil.rmtree(raw, ignore_errors=True)  # a stale file would join the CSV globs
    download_raw(s3, bucket, run_id, raw)
    written, counts = transform(
        raw.as_posix(), Path(args.out) / "clean", expected=expected
    )
    record = {"run_id": run_id, "repairs": counts, "tables": {}}
    for table in written:
        key = f"clean/{run_id}/{table.path.name}"
        s3.upload_file(str(table.path), bucket, key)
        s3.put_object(Bucket=bucket, Key=f"{key}.sha256", Body=table.sha256.encode())
        record["tables"][table.name] = {
            "rows": table.rows,
            "uri": f"s3://{bucket}/{key}",
            "sha256": table.sha256,
        }
    uri = runrecord.write(s3, bucket, run_id, "transform", record)
    print(f"transform: {sum(t.rows for t in written):,} rows, record {uri}", flush=True)
    return 0


def cmd_curate(args) -> int:
    from data_load.curate import curate, download_clean
    from data_load.transform import load_expected

    expected = load_expected()  # compared only on the full data with default sizes
    sizes = {"customers": args.customers, "per_class": args.defect_per_class}
    if args.source:  # local rehearsal: nothing in AWS is read or written
        written, record = curate(
            args.source, Path(args.out), expected=expected, **sizes
        )
        body = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
        (Path(args.out) / "curate.json").write_text(body, encoding="utf-8")
        _print_curated(written, record)
        return 0

    run_id, bucket = require_env("RUN_ID", "TEAM_BUCKET")
    import boto3

    from data_load import runrecord

    s3 = boto3.client("s3")
    runrecord.clear(s3, bucket, run_id, "curate")
    staged = runrecord.read(s3, bucket, run_id, "transform")["tables"]
    clean = Path(args.out) / "clean"
    shutil.rmtree(clean, ignore_errors=True)  # a stale file would be read as a table
    download_clean(s3, bucket, staged, clean)
    written, record = curate(
        clean.as_posix(), Path(args.out) / "curated", expected=expected, **sizes
    )
    record = {"run_id": run_id, **record, "tables": {}}
    for table in written:
        key = f"curated/{run_id}/{table.path.name}"
        s3.upload_file(str(table.path), bucket, key)
        s3.put_object(Bucket=bucket, Key=f"{key}.sha256", Body=table.sha256.encode())
        record["tables"][table.name] = {
            "rows": table.rows,
            "uri": f"s3://{bucket}/{key}",
            "sha256": table.sha256,
        }
    uri = runrecord.write(s3, bucket, run_id, "curate", record)
    _print_curated(written, record)
    print(f"curate: record {uri}", flush=True)
    return 0


def _print_curated(written, record) -> None:
    clean = record["selection"]["customers"]
    cohort = record["defects"]["customers_selected"]
    total = sum(t.rows for t in written)
    print(
        f"curated {clean:,} clean + {cohort:,} defect-cohort customers, {total:,} rows"
    )
    print(f"rules {record['rules']}", flush=True)


def cmd_load(args) -> int:
    run_id, bucket, endpoint, tools_role, write_tools_role = require_env(
        "RUN_ID",
        "TEAM_BUCKET",
        "DSQL_ENDPOINT",
        "TOOLS_ROLE_ARN",
        "WRITE_TOOLS_ROLE_ARN",
    )
    import boto3
    from botocore.exceptions import ClientError

    from data_load import dsql, runrecord

    s3 = boto3.client("s3")
    runrecord.clear(s3, bucket, run_id, "load")
    try:
        staged = runrecord.read(s3, bucket, run_id, "curate")["tables"]
    except (KeyError, ClientError) as e:  # KeyError: the unit tests' fake S3
        if isinstance(e, ClientError) and e.response["Error"]["Code"] != "NoSuchKey":
            raise
        raise SystemExit(f"no curate.json for run {run_id}: run curate first") from None
    plan = load_plan()
    if set(staged) != set(plan.data_tables):
        missing = sorted(set(plan.data_tables) - set(staged))
        raise SystemExit(f"curate.json lacks tables: {', '.join(missing)}")
    # largest first, so the longest load starts first
    order = sorted(staged, key=lambda t: staged[t]["rows"], reverse=True)
    uris = {table: staged[table]["uri"] for table in order}

    conn = dsql.connect(endpoint)
    try:
        dsql.apply_schema(
            conn,
            plan,
            {dsql.READ_ROLE: tools_role, dsql.WRITE_ROLE: write_tools_role},
        )
    finally:
        conn.close()
    dsql.load_all(
        endpoint, uris, dry_run=True
    )  # seconds: catches type mismatches early
    dsql.load_all(endpoint, uris)  # --verify count fails the stage on any shortfall
    conn = dsql.connect(endpoint)  # a DSQL connection lives at most 60 minutes
    try:
        dsql.build_indexes(conn, plan.indexes)
    finally:
        conn.close()
    record = {
        "run_id": run_id,
        "tables": {t: {"rows_loaded": staged[t]["rows"]} for t in order},
    }
    uri = runrecord.write(s3, bucket, run_id, "load", record)
    total = sum(staged[t]["rows"] for t in order)
    print(f"load: {total:,} rows in {len(order)} tables, record {uri}", flush=True)
    return 0


def cmd_access(args) -> int:
    """Create the tool roles, map them to their IAM roles and re-run the grants.

    No table is dropped, so a role added to schema.sql reaches a loaded cluster
    without a reload. CodeBuild runs it with STAGE=access.
    """
    endpoint, tools_role, write_tools_role = require_env(
        "DSQL_ENDPOINT", "TOOLS_ROLE_ARN", "WRITE_TOOLS_ROLE_ARN"
    )
    from data_load import dsql

    plan = load_plan()
    conn = dsql.connect(endpoint)
    try:
        dsql.apply_access(
            conn,
            plan,
            {dsql.READ_ROLE: tools_role, dsql.WRITE_ROLE: write_tools_role},
        )
    finally:
        conn.close()
    print(f"access: roles {', '.join(plan.roles)} mapped and granted", flush=True)
    return 0


def cmd_check(args) -> int:
    import boto3

    from data_load import runrecord, source

    team_s3 = boto3.Session(profile_name=args.team_profile).client("s3")
    record = runrecord.read(team_s3, args.team_bucket, args.run, "ingest")
    origin = record["source"]
    org_s3 = boto3.Session(profile_name=args.bucket_profile).client(
        "s3", region_name=origin["region"]
    )
    current = source.fingerprint(
        org_s3, origin["bucket"], origin["prefix"], list(record["tables"])
    )
    changed = source.drift(
        {t: v["etag_digest"] for t, v in record["tables"].items()},
        {t: digest for t, (_, digest) in current.items()},
    )
    if changed:
        print("changed since the ingest: " + ", ".join(changed))
        return 1
    print(f"no drift: the bucket matches run {args.run}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m data_load")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "ingest", help="stage 1: copy the organizer's CSVs to raw/<run-id>/"
    )
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("transform", help="stage 2: check, repair and write Parquet")
    p.add_argument(
        "--source", help="local directory in the organizer layout (skips S3)"
    )
    p.add_argument("--out", default=str(WORK))
    p.add_argument("--tables", help="comma-separated subset; local runs only")
    p.set_defaults(func=cmd_transform)

    p = sub.add_parser(
        "curate", help="stage 3: fix, select and write the curated Parquet"
    )
    p.add_argument("--source", help="local directory of clean Parquet (skips S3)")
    p.add_argument("--out", default=str(WORK))
    p.add_argument("--customers", type=int, default=1500, help="clean customers (x12)")
    p.add_argument("--defect-per-class", type=int, default=20)
    p.set_defaults(func=cmd_curate)

    p = sub.add_parser("load", help="stage 4: recreate the tables and bulk-load DSQL")
    p.set_defaults(func=cmd_load)

    p = sub.add_parser(
        "access",
        help="create the tool roles, map them to IAM roles and re-run the grants (no reload)",
    )
    p.set_defaults(func=cmd_access)

    p = sub.add_parser(
        "check", help="compare the organizer bucket with a run's ingest record"
    )
    p.add_argument("--run", required=True, help="Step Functions execution name")
    p.add_argument("--team-bucket", required=True)
    p.add_argument("--team-profile", default="ledgerlens")
    p.add_argument("--bucket-profile", default="hackathon")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
