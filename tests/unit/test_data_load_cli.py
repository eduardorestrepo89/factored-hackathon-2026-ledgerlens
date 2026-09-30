"""python -m data_load: argument handling and secret hygiene."""

import json

import pytest
from data_load_fixtures import tx, write_transactions

from data_load.__main__ import RUN_ENV, main, parse_hackathon_secret


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
