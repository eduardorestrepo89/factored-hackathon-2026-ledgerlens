"""python -m data_load: stage commands, their environment, and the load order."""

import json
from pathlib import Path
from unittest import mock

import pytest
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
        (["load"], "RUN_ID, TEAM_BUCKET, DSQL_ENDPOINT, TOOLS_ROLE_ARN"),
    ],
)
def test_stages_list_missing_environment(monkeypatch, command, names):
    for name in (
        "RUN_ID",
        "TEAM_BUCKET",
        "HACKATHON_SECRET_ID",
        "DSQL_ENDPOINT",
        "TOOLS_ROLE_ARN",
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
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    s3 = FakeS3()
    record = {
        "tables": {
            t: {
                "rows": rows,
                "uri": f"s3://team/clean/run-1/{t}.parquet",
                "sha256": "s",
            }
            for t, rows in tables.items()
        }
    }
    runrecord.write(s3, "team", "run-1", "transform", record)
    monkeypatch.setattr("boto3.client", lambda *a, **k: s3)
    calls = []
    monkeypatch.setattr("data_load.dsql.connect", lambda *a, **k: mock.MagicMock())
    monkeypatch.setattr(
        "data_load.dsql.apply_schema",
        lambda conn, plan, arn: calls.append(("schema", arn)),
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
        ("schema", "arn:aws:iam::111111111111:role/ledgerlens-tools"),
        ("dry", order),
        ("load", order),
        ("indexes", 3),
    ]
    loaded = runrecord.read(s3, "team", "run-1", "load")["tables"]
    assert loaded[order[0]] == {"rows_loaded": tables[order[0]]}


@pytest.mark.unit
def test_load_refuses_an_incomplete_transform_record(monkeypatch):
    _, calls = fake_load_env(monkeypatch, {"branches": 350})
    with pytest.raises(
        SystemExit, match="transform.json lacks tables: call_center_interactions"
    ):
        main(["load"])
    assert calls == []  # stopped before touching DSQL
