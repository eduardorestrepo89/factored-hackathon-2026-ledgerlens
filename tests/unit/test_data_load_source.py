"""Source fingerprints: detect a re-upload of the organizer's files."""

from unittest import mock

import pytest

from data_load.source import (
    drift,
    etag_digest,
    fingerprint,
    list_objects,
    source_prefix,
)


def fake_s3(objects_by_prefix):
    s3 = mock.MagicMock()

    def paginate(Bucket, Prefix):
        return [
            {
                "Contents": [
                    {"Key": k, "ETag": f'"{e}"'}
                    for k, e in objects_by_prefix.get(Prefix, [])
                ]
            },
            {},
        ]

    s3.get_paginator.return_value.paginate.side_effect = paginate
    return s3


@pytest.mark.unit
def test_source_prefix_for_event_and_reference_tables():
    assert source_prefix("data/", "bank.transactions") == "data/transactions/"
    assert source_prefix("data/", "pii.customers") == "data/customers.csv"


@pytest.mark.unit
def test_list_objects_reads_every_page_and_strips_quotes():
    s3 = fake_s3({"data/transactions/": [("data/transactions/a.csv", "e1")]})
    assert list_objects(s3, "b", "data/transactions/") == [
        ("data/transactions/a.csv", "e1")
    ]


@pytest.mark.unit
def test_digest_ignores_order_and_catches_rewrites():
    a, b = ("k1", "e1"), ("k2", "e2")
    assert etag_digest([a, b]) == etag_digest([b, a])
    assert etag_digest([a, b]) != etag_digest([a, ("k2", "e3")])
    assert etag_digest([a, b]) != etag_digest([a])


@pytest.mark.unit
def test_fingerprint_counts_files_per_table():
    s3 = fake_s3(
        {
            "data/transactions/": [
                ("data/transactions/1.csv", "e1"),
                ("data/transactions/2.csv", "e2"),
            ],
            "data/customers.csv": [("data/customers.csv", "e3")],
        }
    )
    prints = fingerprint(s3, "b", "data/", ["bank.transactions", "pii.customers"])
    assert prints["bank.transactions"][0] == 2
    assert prints["pii.customers"] == (1, etag_digest([("data/customers.csv", "e3")]))


@pytest.mark.unit
def test_drift_lists_changed_and_one_sided_tables():
    assert drift({"a": "1", "b": "2"}, {"a": "1", "b": "2"}) == []
    assert drift({"a": "1", "b": "2"}, {"a": "1", "b": "X", "c": "3"}) == ["b", "c"]
