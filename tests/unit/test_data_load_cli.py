"""python -m data_load: argument handling and secret hygiene."""

import json
from unittest import mock

import pytest
from data_load_fixtures import tx, write_transactions

from data_load.__main__ import RUN_ENV, main, parse_hackathon_secret
from data_load.stage import Staged


@pytest.mark.unit
def test_stage_command_writes_parquet(tmp_path, capsys):
    write_transactions(
        tmp_path / "src",
        [
            tx("T1", "2026-06-17 10:00:00", "2026-06-17"),
            tx("T2", "2026-06-18 03:00:00", "2026-06-17"),
        ],
    )
    code = main(
        [
            "stage",
            "--source",
            (tmp_path / "src").as_posix(),
            "--out",
            str(tmp_path / "out"),
            "--as-of",
            "2026-06-17T23:59:59",
            "--window-years",
            "2",
            "--tables",
            "bank.transactions",
        ]
    )
    assert code == 0
    assert (tmp_path / "out" / "transactions.parquet").exists()
    assert "total 2 rows in 1 tables" in capsys.readouterr().out


@pytest.mark.unit
def test_run_lists_missing_environment(monkeypatch):
    for name in RUN_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(
        SystemExit,
        match="AS_OF, WINDOW_YEARS, DSQL_ENDPOINT, TEAM_BUCKET, HACKATHON_S3",
    ):
        main(["run"])


@pytest.mark.unit
def test_secret_errors_name_keys_never_values():
    partial = json.dumps(
        {
            "aws_access_key_id": "fake-key-id",
            "aws_secret_access_key": "fake-secret-value",
            "region": "us-east-2",
            "prefix": "data/",
        }
    )
    with pytest.raises(SystemExit) as err:
        parse_hackathon_secret(partial)
    assert str(err.value) == "HACKATHON_S3 is missing: bucket"
    with pytest.raises(SystemExit) as err:
        parse_hackathon_secret(
            '{"aws_secret_access_key": "fake-secret-value"'
        )  # truncated JSON
    assert "fake-secret-value" not in str(err.value)


def fake_run_env(monkeypatch, tmp_path, files=1):
    """Everything cmd_run touches, faked; returns the recorded load_all calls."""
    secret = {
        "aws_access_key_id": "fake-key-id",
        "aws_secret_access_key": "fake-secret-value",
        "bucket": "org-bucket",
        "region": "us-east-2",
        "prefix": "data/",
    }
    env = {
        "AS_OF": "2026-06-17T23:59:59",
        "WINDOW_YEARS": "2",
        "DSQL_ENDPOINT": "c.dsql.us-east-1.on.aws",
        "TEAM_BUCKET": "team-bucket",
        "HACKATHON_S3": json.dumps(secret),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    staged = [
        Staged("bank.transactions", tmp_path / "transactions.parquet", 5, "a" * 64),
        Staged("pii.customers", tmp_path / "customers.parquet", 3, "b" * 64),
    ]
    monkeypatch.setattr("data_load.__main__.stage", lambda *a, **k: staged)
    monkeypatch.setattr("boto3.client", lambda *a, **k: mock.MagicMock())
    monkeypatch.setattr(
        "data_load.source.fingerprint",
        lambda s3, bucket, prefix, tables: {t: (files, "d" * 64) for t in tables},
    )
    monkeypatch.setattr("data_load.dsql.connect", lambda *a, **k: mock.MagicMock())
    for name in ("apply_schema", "build_indexes", "record_manifest"):
        monkeypatch.setattr(f"data_load.dsql.{name}", lambda *a, **k: None)
    loads = []
    monkeypatch.setattr(
        "data_load.dsql.load_all",
        lambda endpoint, uris, dry_run=False: loads.append((dry_run, list(uris))),
    )
    return loads


@pytest.mark.unit
def test_run_dry_runs_every_table_before_loading(monkeypatch, tmp_path):
    loads = fake_run_env(monkeypatch, tmp_path)
    assert main(["run", "--out", str(tmp_path)]) == 0
    tables = ["bank.transactions", "pii.customers"]
    assert loads == [(True, tables), (False, tables)]


@pytest.mark.unit
def test_run_refuses_tables_with_no_source_files(monkeypatch, tmp_path):
    loads = fake_run_env(monkeypatch, tmp_path, files=0)
    with pytest.raises(
        SystemExit, match="no source files: bank.transactions, pii.customers"
    ):
        main(["run", "--out", str(tmp_path)])
    assert loads == []  # stopped before touching DSQL
