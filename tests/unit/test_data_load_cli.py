"""python -m data_load: stage commands, their environment, and the load order."""

import hashlib
import json
from pathlib import Path
from unittest import mock

import pytest
from curate_fixtures import PERSONAS, world
from data_load_fixtures import tx, write_transactions
from data_load_s3 import FakeS3

from data_load import runrecord
from data_load.__main__ import main
from data_load.ddl import load_plan
from data_load.source import EVENT_TABLES, etag_digest, source_prefix
from data_load.transform import Table, load_expected


@pytest.mark.unit
def test_transform_command_writes_parquet_locally(tmp_path, capsys):
    write_transactions(
        tmp_path / "src",
        [
            tx("T1", "2026-06-17 10:00:00", "2026-06-17"),
            tx("T2", "2026-06-18 03:00:00", "2026-06-17"),
        ],
    )
    code = main(
        [
            "transform",
            "--source",
            (tmp_path / "src").as_posix(),
            "--out",
            str(tmp_path / "out"),
            "--tables",
            "transactions",
        ]
    )
    assert code == 0
    assert (tmp_path / "out" / "transactions.parquet").exists()
    assert "total 2 rows in 1 tables" in capsys.readouterr().out


@pytest.mark.unit
def test_tables_subset_is_for_local_runs_only():
    with pytest.raises(SystemExit, match="only for local runs"):
        main(["transform", "--tables", "transactions"])


@pytest.mark.unit
@pytest.mark.parametrize(
    "command, names",
    [
        (["ingest"], "RUN_ID, TEAM_BUCKET, HACKATHON_SECRET_ID"),
        (["transform"], "RUN_ID, TEAM_BUCKET"),
        (["curate"], "RUN_ID, TEAM_BUCKET"),
        (
            ["load"],
            "RUN_ID, TEAM_BUCKET, DSQL_ENDPOINT, TOOLS_ROLE_ARN, WRITE_TOOLS_ROLE_ARN",
        ),
        (["access"], "DSQL_ENDPOINT, TOOLS_ROLE_ARN, WRITE_TOOLS_ROLE_ARN"),
    ],
)
def test_stages_list_missing_environment(monkeypatch, command, names):
    for name in (
        "RUN_ID",
        "TEAM_BUCKET",
        "HACKATHON_SECRET_ID",
        "DSQL_ENDPOINT",
        "TOOLS_ROLE_ARN",
        "WRITE_TOOLS_ROLE_ARN",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match=f"missing environment variables: {names}$"):
        main(command)


@pytest.mark.unit
def test_cloud_transform_starts_clean_uploads_parquet_and_records(
    monkeypatch, tmp_path
):
    for name, value in {"RUN_ID": "run-1", "TEAM_BUCKET": "team"}.items():
        monkeypatch.setenv(name, value)
    s3 = FakeS3({("team", "raw/run-1/customers.csv"): b"c"})
    monkeypatch.setattr("boto3.client", lambda *a, **k: s3)
    stale = tmp_path / "raw" / "transactions" / "stale.csv"  # left by an earlier run
    stale.parent.mkdir(parents=True)
    stale.write_text("old run")
    seen = {}

    def fake_transform(source, out_dir, expected=None, **kwargs):
        files = Path(source).rglob("*")
        seen["files"] = sorted(
            p.relative_to(source).as_posix() for p in files if p.is_file()
        )
        seen["expected"] = expected
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "customers.parquet"
        path.write_bytes(b"parquet")
        return [Table("customers", path, 150_000, "s" * 64)], {
            "R1": {"resolved": 1, "set_null": 0}
        }

    monkeypatch.setattr("data_load.transform.transform", fake_transform)
    assert main(["transform", "--out", str(tmp_path)]) == 0
    assert seen["files"] == ["customers.csv"]  # the stale file is gone
    assert seen["expected"] == load_expected()
    assert s3.objects[("team", "clean/run-1/customers.parquet")] == b"parquet"
    assert s3.objects[("team", "clean/run-1/customers.parquet.sha256")] == b"s" * 64
    record = runrecord.read(s3, "team", "run-1", "transform")
    assert record["tables"]["customers"] == {
        "rows": 150_000,
        "uri": "s3://team/clean/run-1/customers.parquet",
        "sha256": "s" * 64,
    }
    assert record["repairs"] == {"R1": {"resolved": 1, "set_null": 0}}


@pytest.mark.unit
def test_ingest_takes_the_organizer_keys_from_secrets_manager(monkeypatch, capsys):
    secret = {
        "aws_access_key_id": "fake-key-id",
        "aws_secret_access_key": "fake-secret-value",
        "bucket": "org",
        "region": "us-east-2",
        "prefix": "data/",
    }
    org = FakeS3(
        {
            (
                "org",
                source_prefix("data/", t) + ("x.csv" if t in EVENT_TABLES else ""),
            ): b"x"
            for t in load_plan().data_tables
        }
    )
    team, clients = FakeS3(), []

    class Secrets:
        def get_secret_value(self, SecretId):
            assert SecretId == "ledgerlens/hackathon-s3"
            return {"SecretString": json.dumps(secret)}

    def client(service, **kwargs):
        clients.append((service, kwargs.get("aws_access_key_id")))
        if service == "secretsmanager":
            return Secrets()
        return org if kwargs.get("aws_access_key_id") else team

    monkeypatch.setattr("boto3.client", client)
    monkeypatch.delenv("HACKATHON_S3", raising=False)
    for name, value in {
        "RUN_ID": "run-1",
        "TEAM_BUCKET": "team",
        "HACKATHON_SECRET_ID": "ledgerlens/hackathon-s3",
    }.items():
        monkeypatch.setenv(name, value)
    assert main(["ingest"]) == 0
    assert ("s3", "fake-key-id") in clients  # organizer reads use the organizer's keys
    record = runrecord.read(team, "team", "run-1", "ingest")
    assert len(record["tables"]) == 13
    assert "fake-secret-value" not in capsys.readouterr().out


@pytest.mark.unit
@pytest.mark.parametrize("stage", ["ingest", "transform", "curate", "load"])
def test_a_failed_rerun_removes_the_stages_old_record(monkeypatch, stage):
    env = {
        "RUN_ID": "run-1",
        "TEAM_BUCKET": "team",
        "HACKATHON_SECRET_ID": "ledgerlens/hackathon-s3",
        "DSQL_ENDPOINT": "c.dsql.us-east-1.on.aws",
        "TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-tools",
        "WRITE_TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-write-tools",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    s3 = FakeS3()
    runrecord.write(s3, "team", "run-1", stage, {"from": "an earlier success"})
    monkeypatch.setattr("boto3.client", lambda *a, **k: s3)

    def fail(*args, **kwargs):
        raise RuntimeError("stage failed")

    # each stage's first real step fails
    monkeypatch.setattr("data_load.ingest.load_secret", fail)
    monkeypatch.setattr("data_load.transform.download_raw", fail)
    monkeypatch.setattr("data_load.runrecord.read", fail)
    with pytest.raises(RuntimeError, match="stage failed"):
        main([stage])
    # a record means the stage finished: the stale success must not outlive the rerun
    assert ("team", f"runs/run-1/{stage}.json") not in s3.objects


def fake_check_env(monkeypatch, org_files):
    """cmd_check reads ingest.json with one profile and the organizer bucket with another."""
    team, org = FakeS3(), FakeS3(org_files)
    objects = [["data/customers.csv", "etag-data/customers.csv", 1]]
    record = {
        "source": {"bucket": "org", "prefix": "data/", "region": "us-east-2"},
        "tables": {"customers": {"etag_digest": etag_digest(objects)}},
    }
    runrecord.write(team, "team", "run-1", "ingest", record)
    sessions = {"ledgerlens": team, "hackathon": org}

    class Session:
        def __init__(self, profile_name):
            self.profile = profile_name

        def client(self, service, **kwargs):
            return sessions[self.profile]

    monkeypatch.setattr("boto3.Session", Session)


@pytest.mark.unit
def test_check_reports_no_drift_when_the_bucket_is_unchanged(monkeypatch, capsys):
    fake_check_env(monkeypatch, {("org", "data/customers.csv"): b"c"})
    assert main(["check", "--run", "run-1", "--team-bucket", "team"]) == 0
    assert "no drift: the bucket matches run run-1" in capsys.readouterr().out


@pytest.mark.unit
def test_check_names_tables_that_changed_since_the_ingest(monkeypatch, capsys):
    # a second object under the customers prefix changes the ETag digest
    fake_check_env(
        monkeypatch,
        {("org", "data/customers.csv"): b"c", ("org", "data/customers.csv.bak"): b"x"},
    )
    assert main(["check", "--run", "run-1", "--team-bucket", "team"]) == 1
    assert "changed since the ingest: customers" in capsys.readouterr().out


def fake_load_env(monkeypatch, tables):
    """Everything cmd_load touches, faked; returns the S3 fake and recorded calls."""
    env = {
        "RUN_ID": "run-1",
        "TEAM_BUCKET": "team",
        "DSQL_ENDPOINT": "c.dsql.us-east-1.on.aws",
        "TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-tools",
        "WRITE_TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-write-tools",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    s3 = FakeS3()
    record = {
        "tables": {
            t: {
                "rows": rows,
                "uri": f"s3://team/curated/run-1/{t}.parquet",
                "sha256": "s",
            }
            for t, rows in tables.items()
        }
    }
    runrecord.write(s3, "team", "run-1", "curate", record)
    monkeypatch.setattr("boto3.client", lambda *a, **k: s3)
    calls = []
    monkeypatch.setattr("data_load.dsql.connect", lambda *a, **k: mock.MagicMock())
    monkeypatch.setattr(
        "data_load.dsql.apply_schema",
        lambda conn, plan, role_arns: calls.append(("schema", role_arns)),
    )
    monkeypatch.setattr(
        "data_load.dsql.load_all",
        lambda endpoint, uris, dry_run=False: calls.append(
            ("dry" if dry_run else "load", list(uris))
        ),
    )
    monkeypatch.setattr(
        "data_load.dsql.build_indexes",
        lambda conn, stmts: calls.append(("indexes", len(stmts))),
    )
    return s3, calls


@pytest.mark.unit
def test_load_dry_runs_every_table_largest_first_then_loads(monkeypatch):
    tables = {t: i for i, t in enumerate(load_plan().data_tables)}
    s3, calls = fake_load_env(monkeypatch, tables)
    assert main(["load"]) == 0
    order = sorted(tables, key=tables.get, reverse=True)
    assert calls == [
        (
            "schema",
            {
                "ll_read": "arn:aws:iam::111111111111:role/ledgerlens-tools",
                "ll_write": "arn:aws:iam::111111111111:role/ledgerlens-write-tools",
            },
        ),
        ("dry", order),
        ("load", order),
        ("indexes", 3),
    ]
    loaded = runrecord.read(s3, "team", "run-1", "load")["tables"]
    assert loaded[order[0]] == {"rows_loaded": tables[order[0]]}


@pytest.mark.unit
def test_load_refuses_an_incomplete_curate_record(monkeypatch):
    _, calls = fake_load_env(monkeypatch, {"branches": 350})
    with pytest.raises(
        SystemExit, match="curate.json lacks tables: call_center_interactions"
    ):
        main(["load"])
    assert calls == []  # stopped before touching DSQL


@pytest.mark.unit
def test_load_without_a_curate_record_says_to_run_curate_first(monkeypatch):
    s3, calls = fake_load_env(monkeypatch, {"branches": 350})
    runrecord.clear(s3, "team", "run-1", "curate")
    with pytest.raises(
        SystemExit, match="no curate.json for run run-1: run curate first"
    ):
        main(["load"])
    assert calls == []


@pytest.mark.unit
def test_curate_command_writes_parquet_locally(monkeypatch, tmp_path, capsys):
    source = world(tmp_path / "clean")
    monkeypatch.setattr("data_load.curate_select.load_personas", lambda: PERSONAS)
    code = main(
        [
            "curate",
            "--source",
            source.as_posix(),
            "--out",
            str(tmp_path / "out"),
            "--customers",
            "12",
            "--defect-per-class",
            "1",
        ]
    )
    assert code == 0
    assert (tmp_path / "out" / "customers.parquet").exists()
    record = json.loads((tmp_path / "out" / "curate.json").read_text(encoding="utf-8"))
    assert record["selection"]["personas"] == {"P01": "PER"}
    assert "curated 2 clean + 1 defect-cohort customers" in capsys.readouterr().out


@pytest.mark.unit
def test_cloud_curate_downloads_checks_uploads_and_records(monkeypatch, tmp_path):
    for name, value in {"RUN_ID": "run-1", "TEAM_BUCKET": "team"}.items():
        monkeypatch.setenv(name, value)
    s3 = FakeS3({("team", "clean/run-1/branches.parquet"): b"clean"})
    sha = hashlib.sha256(b"clean").hexdigest()
    staged = {"uri": "s3://team/clean/run-1/branches.parquet", "sha256": sha}
    runrecord.write(s3, "team", "run-1", "transform", {"tables": {"branches": staged}})
    monkeypatch.setattr("boto3.client", lambda *a, **k: s3)
    seen = {}

    def fake_curate(source, out_dir, expected=None, **sizes):
        seen["files"] = sorted(p.name for p in Path(source).iterdir())
        seen["sizes"], seen["expected"] = sizes, expected
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "branches.parquet"
        path.write_bytes(b"curated")
        record = {
            "as_of": "2026-06-17T23:59:59",
            "rules": {"C1": {"changed": 1}},
            "selection": {"customers": 1500},
            "defects": {"customers_selected": 159},
        }
        return [Table("branches", path, 350, "c" * 64)], record

    monkeypatch.setattr("data_load.curate.curate", fake_curate)
    assert main(["curate", "--out", str(tmp_path)]) == 0
    assert seen["files"] == ["branches.parquet"]
    assert seen["sizes"] == {"customers": 1500, "per_class": 20}
    assert seen["expected"] == load_expected()
    assert s3.objects[("team", "curated/run-1/branches.parquet")] == b"curated"
    assert s3.objects[("team", "curated/run-1/branches.parquet.sha256")] == b"c" * 64
    record = runrecord.read(s3, "team", "run-1", "curate")
    assert record["run_id"] == "run-1"
    assert record["rules"] == {"C1": {"changed": 1}}
    assert record["tables"]["branches"] == {
        "rows": 350,
        "uri": "s3://team/curated/run-1/branches.parquet",
        "sha256": "c" * 64,
    }


@pytest.mark.unit
def test_access_applies_roles_mappings_and_grants_only(monkeypatch, capsys):
    env = {
        "DSQL_ENDPOINT": "c.dsql.us-east-1.on.aws",
        "TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-tools",
        "WRITE_TOOLS_ROLE_ARN": "arn:aws:iam::111111111111:role/ledgerlens-write-tools",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    conn = mock.MagicMock()
    calls = []
    monkeypatch.setattr("data_load.dsql.connect", lambda endpoint: conn)
    monkeypatch.setattr(
        "data_load.dsql.apply_access",
        lambda c, plan, role_arns: calls.append((c, set(plan.roles), role_arns)),
    )
    monkeypatch.setattr(
        "data_load.dsql.apply_schema",
        lambda *a: pytest.fail("access must not recreate the tables"),
    )

    assert main(["access"]) == 0

    assert calls == [
        (
            conn,
            {"ll_read", "ll_write"},
            {
                "ll_read": env["TOOLS_ROLE_ARN"],
                "ll_write": env["WRITE_TOOLS_ROLE_ARN"],
            },
        )
    ]
    conn.close.assert_called_once()
    assert (
        "access: roles ll_read, ll_write mapped and granted" in capsys.readouterr().out
    )
