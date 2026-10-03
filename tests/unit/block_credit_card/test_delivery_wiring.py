"""Tests for the dependency wiring of the block_credit_card tool."""

from datetime import datetime, timezone

import block_credit_card_lambda.utils.connectors.dsql as dsql_module
import pytest
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.delivery.dependencies import dependencies_builder
from block_credit_card_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_block_credit_card_use_case,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_query_provider,
    build_settings,
)
from block_credit_card_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from block_credit_card_lambda.domain.entities.card_block import CardBlock
from block_credit_card_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from block_credit_card_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import CUSTOMER_ID, QUERY_NAMES, FakeConnector, make_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
SETTINGS = DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL)
NOW = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
ARGS = {
    "customer_id": CUSTOMER_ID,
    "card_last4": "4821",
    "reason": "lost",
    "customer_confirmed": True,
}


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_dsql_settings_connects_as_the_write_role_by_default() -> None:
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ll_write"
    )


def test_build_connector_returns_a_dsql_connector_without_touching_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_boto3(*args: object, **kwargs: object) -> object:
        raise AssertionError("boto3 client created while building the connector")

    monkeypatch.setattr(dsql_module.boto3, "client", no_boto3)

    assert isinstance(build_connector(SETTINGS, ENV), DsqlConnector)


def test_aurora_dsql_runs_the_postgresql_sql_dialect() -> None:
    assert SQL_DIALECTS == {DatabaseEngine.AURORA_DSQL: "postgresql"}
    provider = build_query_provider(DatabaseEngine.AURORA_DSQL)

    assert provider is build_query_provider(DatabaseEngine.AURORA_DSQL)
    assert "UPDATE products" in provider.get("block_credit_card")


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "block_credit_card_lambda"


def test_build_database_repository_wraps_the_connector_for_the_engine() -> None:
    repository = build_database_repository(DatabaseEngine.AURORA_DSQL, FakeConnector())

    assert isinstance(repository, DsqlRepository)


def test_build_database_repository_rejects_an_unknown_engine() -> None:
    with pytest.raises(ConfigurationError):
        build_database_repository("oracle", FakeConnector())  # type: ignore[arg-type]


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
    connector = FakeConnector(([make_row()], [{"product_id": "PRD-1"}]))
    use_fake_connector(monkeypatch, connector)

    use_case = build_block_credit_card_use_case(ENV)
    assert isinstance(use_case, BlockCreditCardUseCase)

    assert use_case.execute(**ARGS, now=NOW) == CardBlock(
        card_last4="4821", status="Blocked", already_blocked=False
    )
    find, update = connector.connections[-1].cursors
    assert "FROM products" in find.executed[0][0]
    assert "UPDATE products" in update.executed[0][0]


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_block_credit_card_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        DataSourceConnectionError("no route to host"),
        [make_row(product_status="Blocked")],
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_block_credit_card_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(**ARGS, now=NOW).already_blocked is True


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**ENV, "DB_ENGINE": "oracle"},
        {"AWS_REGION": "us-east-1"},
        {"DSQL_CLUSTER_ENDPOINT": ENDPOINT},
        {**ENV, "DSQL_CLUSTER_ENDPOINT": f"https://{ENDPOINT}"},
    ],
)
def test_use_case_build_with_bad_configuration_returns_none(
    env: dict[str, str],
) -> None:
    assert build_block_credit_card_use_case(env) is None


def test_build_clock_reads_as_of() -> None:
    assert build_clock({"AS_OF": "2026-03-14"}) == ClockSettings(
        as_of=datetime(2026, 3, 14, tzinfo=timezone.utc)
    )


def test_build_clock_with_a_bad_as_of_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for block_credit_card" in caplog.text
