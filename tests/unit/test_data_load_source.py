"""Source listing and fingerprints: detect a re-upload of the organizer's files."""

import pytest
from data_load_s3 import FakeS3

from data_load.source import (
    drift,
    etag_digest,
    fingerprint,
    list_objects,
    source_prefix,
)


@pytest.mark.unit
def test_source_prefix_for_event_and_reference_tables():
    assert source_prefix("data/", "transactions") == "data/transactions/"
    assert source_prefix("data/", "customers") == "data/customers.csv"


@pytest.mark.unit
def test_source_prefix_tolerates_missing_or_extra_slashes():
    assert source_prefix("data", "transactions") == "data/transactions/"
    assert source_prefix("/data/", "customers") == "data/customers.csv"


@pytest.mark.unit
def test_list_objects_returns_key_etag_and_size():
    s3 = FakeS3({("b", "data/transactions/a.csv"): b"abc"})
    assert list_objects(s3, "b", "data/transactions/") == [
        ("data/transactions/a.csv", "etag-data/transactions/a.csv", 3)
    ]


@pytest.mark.unit
def test_digest_ignores_order_and_size_and_catches_rewrites():
    a, b = ("k1", "e1", 1), ("k2", "e2", 2)
    assert etag_digest([a, b]) == etag_digest([b, a])
    assert etag_digest([a, b]) == etag_digest([a, ("k2", "e2", 99)])
    assert etag_digest([a, b]) != etag_digest([a, ("k2", "e3", 2)])
    assert etag_digest([a, b]) != etag_digest([a])


@pytest.mark.unit
def test_fingerprint_counts_files_per_table():
    s3 = FakeS3(
        {
            ("b", "data/transactions/1.csv"): b"1",
            ("b", "data/transactions/2.csv"): b"2",
            ("b", "data/customers.csv"): b"3",
        }
    )
    prints = fingerprint(s3, "b", "data/", ["transactions", "customers"])
    assert prints["transactions"][0] == 2
    assert prints["customers"] == (
        1,
        etag_digest([("data/customers.csv", "etag-data/customers.csv", 1)]),
    )


@pytest.mark.unit
def test_drift_lists_changed_and_one_sided_tables():
    assert drift({"a": "1", "b": "2"}, {"a": "1", "b": "2"}) == []
    assert drift({"a": "1", "b": "2"}, {"a": "1", "b": "X", "c": "3"}) == ["b", "c"]
