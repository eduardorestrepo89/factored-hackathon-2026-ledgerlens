"""The curate stage end to end on tiny Parquet tables (curate spec sections 4 and 8)."""

import duckdb
import pytest
from curate_fixtures import PERSONAS, world
from data_load_s3 import FakeS3

from data_load.curate import curate, download_clean
from data_load.curate_rules import CurationError
from data_load.transform import sha256_file


def read(path, sql):
    return duckdb.sql(sql.replace("{t}", f"'{path.as_posix()}'")).fetchall()


@pytest.mark.unit
def test_curate_writes_clean_customers_fixed_and_the_cohort_as_delivered(tmp_path):
    source = world(tmp_path / "clean")
    written, record = curate(
        source.as_posix(),
        tmp_path / "out",
        customers=12,
        per_class=1,
        personas=PERSONAS,
    )
    files = {t.name: t for t in written}
    assert set(files) == {
        "customers",
        "service_agents",
        "products",
        "branches",
        "marketing_campaigns",
        "transactions",
        "call_center_interactions",
        "call_transcripts",
        "satisfaction_surveys",
        "digital_events",
        "complaints",
        "campaign_sends",
    }
    customers = read(files["customers"].path, "SELECT customer_id FROM {t} ORDER BY 1")
    # one per cell: the persona wins its cell, OK2 is alone in Argentina, DEF is the cohort
    assert customers == [("DEF",), ("OK2",), ("PER",)]
    countries = dict(
        read(
            files["transactions"].path,
            "SELECT transaction_id, transaction_country FROM {t}",
        )
    )
    assert countries["T-PER-MX"] == "México"  # clean: C1 applied
    assert countries["T-DEF-MX"] == "Mexico"  # cohort: kept as transform wrote it
    assert read(files["call_transcripts"].path, "SELECT transcript_id FROM {t}") == [
        ("R1",)
    ]
    assert read(files["digital_events"].path, "SELECT event_id FROM {t}") == [("E1",)]
    assert read(files["branches"].path, "SELECT count(*) FROM {t}") == [(1,)]
    assert record["selection"]["customers"] == 2
    assert record["selection"]["personas"] == {"P01": "PER"}
    assert record["defects"]["customers"]["DEF"] == {
        "K09": ["T-DEF-MX"],
        "K17": ["DEF"],
    }
    assert record["rules"]["C1"] == {"changed": 2}  # rules count every row
    assert files["customers"].sha256 == sha256_file(files["customers"].path)


@pytest.mark.unit
@pytest.mark.parametrize("customers", [0, 100])
def test_customer_counts_must_fill_the_12_cells_evenly(tmp_path, customers):
    with pytest.raises(CurationError, match="positive multiple of 12"):
        curate(str(tmp_path), tmp_path / "out", customers=customers, personas=PERSONAS)


@pytest.mark.unit
def test_full_runs_must_match_the_pinned_curation_counts(tmp_path):
    source = world(tmp_path / "clean")
    rows_in = {
        "branches": 1,
        "service_agents": 0,
        "marketing_campaigns": 0,
        "customers": 5,
        "products": 4,
        "transactions": 6,
        "call_center_interactions": 2,
        "call_transcripts": 2,
        "satisfaction_surveys": 0,
        "digital_events": 2,
        "complaints": 0,
        "campaign_sends": 0,
    }
    expected = {"rows": rows_in, "curation": {"rules": {}, "rows": {}}}
    with pytest.raises(CurationError, match="differs from expected.json curation"):
        curate(
            source.as_posix(), tmp_path / "out", personas=PERSONAS, expected=expected
        )


@pytest.mark.unit
def test_a_clean_customer_breaking_a_rule_fails_the_stage(tmp_path, monkeypatch):
    source = world(tmp_path / "clean")
    from data_load import curate_rules

    def without_c1(con):
        return {rule: fix(con) for rule, _, fix in curate_rules.RULES if rule != "C1"}

    monkeypatch.setattr("data_load.curate_rules.apply_rules", without_c1)
    with pytest.raises(CurationError, match="C1: 1 rows of clean customers break it"):
        curate(
            source.as_posix(),
            tmp_path / "out",
            customers=12,
            per_class=1,
            personas=PERSONAS,
        )


@pytest.mark.unit
def test_download_clean_rejects_a_file_that_differs_from_transform_json(tmp_path):
    s3 = FakeS3({("team", "clean/run-1/branches.parquet"): b"parquet"})
    staged = {
        "branches": {
            "uri": "s3://team/clean/run-1/branches.parquet",
            "sha256": "0" * 64,
        }
    }
    with pytest.raises(CurationError, match="branches: Parquet differs"):
        download_clean(s3, "team", staged, tmp_path)
