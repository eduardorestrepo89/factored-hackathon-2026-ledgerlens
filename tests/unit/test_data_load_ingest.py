"""Stage 1: byte-for-byte copy of the organizer's files, secret hygiene, lineage record."""

import json

import pytest
from data_load_s3 import FakeS3

from data_load.ingest import IngestError, ingest, load_secret, parse_secret
from data_load.source import etag_digest

SECRET = {
    "aws_access_key_id": "fake-key-id",
    "aws_secret_access_key": "fake-secret-value",
    "bucket": "org",
    "region": "us-east-2",
    "prefix": "data/",
}
ORG_FILES = {
    (
        "org",
        "data/transactions/year=2024/month=06/day=18/transactions_20240618.csv",
    ): b"t1",
    (
        "org",
        "data/transactions/year=2024/month=06/day=19/transactions_20240619.csv",
    ): b"t22",
    ("org", "data/customers.csv"): b"c333",
    ("org", "data_backup_20260831/customers.csv"): b"old",  # outside the prefix
}


class FakeSecrets:
    def __init__(self, value: str):
        self.value, self.asked = value, []

    def get_secret_value(self, SecretId):
        self.asked.append(SecretId)
        return {"SecretString": self.value}


@pytest.mark.unit
def test_copies_every_file_under_the_run_prefix():
    org, team = FakeS3(ORG_FILES), FakeS3()
    ingest(org, team, SECRET, "team", "run-1", ["transactions", "customers"])
    assert team.keys("team") == [
        "raw/run-1/customers.csv",
        "raw/run-1/transactions/year=2024/month=06/day=18/transactions_20240618.csv",
        "raw/run-1/transactions/year=2024/month=06/day=19/transactions_20240619.csv",
    ]
    assert team.objects[("team", "raw/run-1/customers.csv")] == b"c333"


@pytest.mark.unit
def test_record_holds_counts_bytes_and_digest_per_table():
    record = ingest(
        FakeS3(ORG_FILES), FakeS3(), SECRET, "team", "run-1", ["transactions"]
    )
    tx = record["tables"]["transactions"]
    assert (tx["files"], tx["bytes"]) == (2, 5)
    assert tx["etag_digest"] == etag_digest([tuple(o) for o in tx["objects"]])
    assert record["raw_prefix"] == "s3://team/raw/run-1/"
    assert record["source"] == {
        "bucket": "org",
        "prefix": "data/",
        "region": "us-east-2",
    }
    assert "fake-secret-value" not in json.dumps(record)


@pytest.mark.unit
def test_a_table_without_files_stops_before_copying():
    team = FakeS3()
    with pytest.raises(IngestError, match="no source files: complaints"):
        ingest(
            FakeS3(ORG_FILES),
            team,
            SECRET,
            "team",
            "run-1",
            ["customers", "complaints"],
        )
    assert team.keys("team") == []


@pytest.mark.unit
def test_a_short_copy_fails_the_stage():
    team = FakeS3()
    team.truncate.add("raw/run-1/customers.csv")
    with pytest.raises(IngestError, match=r"data/customers.csv \(3 of 4 bytes\)"):
        ingest(FakeS3(ORG_FILES), team, SECRET, "team", "run-1", ["customers"])


@pytest.mark.unit
def test_secret_comes_from_secrets_manager():
    secrets = FakeSecrets(json.dumps(SECRET))
    assert load_secret(secrets, "ledgerlens/hackathon-s3") == SECRET
    assert secrets.asked == ["ledgerlens/hackathon-s3"]


@pytest.mark.unit
def test_secret_errors_name_keys_never_values():
    partial = {k: v for k, v in SECRET.items() if k != "bucket"}
    with pytest.raises(IngestError) as err:
        parse_secret(json.dumps(partial))
    assert str(err.value) == "the organizer secret is missing: bucket"
    with pytest.raises(IngestError) as err:
        parse_secret('{"aws_secret_access_key": "fake-secret-value"')  # truncated JSON
    assert "fake-secret-value" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
