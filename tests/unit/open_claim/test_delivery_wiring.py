"""Tests for the dependency wiring of the open_claim tool."""

from datetime import datetime, timezone

import pytest
from open_claim_lambda.application.use_cases.open_claim import OpenClaimUseCase
from open_claim_lambda.delivery.dependencies import dependencies_builder
from open_claim_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_clock,
    build_dsql_settings,
    build_open_claim_use_case,
    build_query_provider,
    build_settings,
)
from open_claim_lambda.delivery.settings import (
    ClockSettings,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from open_claim_lambda.domain.entities.claim import ResolutionEstimate

from .fakes import CUSTOMER_ID, QUERY_NAMES, FakeConnector, make_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
NOW = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
ARGS = {
    "customer_id": CUSTOMER_ID,
    "transaction_ids": ["TRX-1"],
    "claim_type": "fraud",
    "customer_statement": "No lo reconozco",
    "customer_confirmed": True,
}


def test_build_settings_and_the_write_role_default() -> None:
    assert build_settings(ENV) == DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL)
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ll_write"
    )


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    assert QUERIES_ROOT.parent.name == "open_claim_lambda"
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()
    assert "INSERT INTO complaints" in build_query_provider(
        DatabaseEngine.AURORA_DSQL
    ).get("insert_claim")


def use_fake_connector(
    monkeypatch: pytest.MonkeyPatch, connector: FakeConnector
) -> None:
    """Make the builder hand out ``connector`` instead of a real DSQL one."""
    monkeypatch.setattr(
        dependencies_builder, "build_connector", lambda _settings, _env: connector
    )


def test_use_case_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        (
            [make_row()],
            [{"complaint_id": "CMP-X"}],
            [{"median_days": 4.2, "p90_days": 11.5}],
        )
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_open_claim_use_case(ENV)
    assert isinstance(use_case, OpenClaimUseCase)
    result = use_case.execute(**ARGS, now=NOW)

    assert result.claims[0].card_last4 == "4821"
    assert result.resolution_estimate == ResolutionEstimate(median_days=5, p90_days=12)
    sqls = [c.executed[0][0] for c in connector.connections[-1].cursors]
    assert "FROM transactions" in sqls[0]
    assert "INSERT INTO complaints" in sqls[1]
    assert "percentile_cont" in sqls[2]


@pytest.mark.parametrize(
    "env",
    [{}, {**ENV, "DB_ENGINE": "oracle"}, {"AWS_REGION": "us-east-1"}],
)
def test_use_case_build_with_bad_configuration_returns_none(
    env: dict[str, str],
) -> None:
    assert build_open_claim_use_case(env) is None


def test_build_clock_reads_as_of_and_rejects_a_bad_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "2026-03-14"}) == ClockSettings(
        as_of=datetime(2026, 3, 14, tzinfo=timezone.utc)
    )
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for open_claim" in caplog.text
