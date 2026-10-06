"""Tests for the dependency wiring of the list_credit_cards tool."""

from datetime import datetime, timezone

import list_credit_cards_lambda.utils.connectors.dsql as dsql_module
import pytest
from list_credit_cards_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from list_credit_cards_lambda.application.use_cases.list_credit_cards import (
    ListCreditCardsUseCase,
)
from list_credit_cards_lambda.delivery.dependencies import dependencies_builder
from list_credit_cards_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_list_credit_cards_use_case,
    build_query_provider,
    build_settings,
)
from list_credit_cards_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from list_credit_cards_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from list_credit_cards_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import CUSTOMER_ID, FakeConnector, make_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
SETTINGS = DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL, max_rows=25)


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_dsql_settings_reads_the_environment() -> None:
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ll_read"
    )


def test_build_connector_returns_a_dsql_connector_without_touching_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_boto3(*args: object, **kwargs: object) -> object:
        raise AssertionError("boto3 client created while building the connector")

    monkeypatch.setattr(dsql_module.boto3, "client", no_boto3)

    assert isinstance(build_connector(SETTINGS, ENV), DsqlConnector)


def test_build_connector_reads_the_dsql_settings() -> None:
    with pytest.raises(ConfigurationError, match="DSQL_CLUSTER_ENDPOINT"):
        build_connector(SETTINGS, {"AWS_REGION": "us-east-1"})


def test_aurora_dsql_runs_the_postgresql_sql_dialect() -> None:
    assert SQL_DIALECTS == {DatabaseEngine.AURORA_DSQL: "postgresql"}
    provider = build_query_provider(DatabaseEngine.AURORA_DSQL)

    assert provider is build_query_provider(DatabaseEngine.AURORA_DSQL)
    assert "DISTINCT ON" in provider.get("list_credit_cards")


def test_every_engine_has_a_dialect_folder_with_the_sql() -> None:
    for engine in DatabaseEngine:
        sql_file = QUERIES_ROOT / SQL_DIALECTS[engine] / "list_credit_cards.sql"
        assert sql_file.is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "list_credit_cards_lambda"


def test_build_query_provider_rejects_an_engine_without_a_dialect() -> None:
    with pytest.raises(ConfigurationError):
        build_query_provider("oracle")  # type: ignore[arg-type]


def test_build_database_repository_wraps_the_connector_for_the_engine() -> None:
    database_repository = build_database_repository(
        DatabaseEngine.AURORA_DSQL, FakeConnector()
    )

    assert isinstance(database_repository, DsqlRepository)


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
    connector = FakeConnector([make_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_credit_cards_use_case(ENV)
    assert isinstance(use_case, ListCreditCardsUseCase)
    result = use_case.execute(CUSTOMER_ID)

    assert result.cards[0].card_last4 == "4821"
    executed_sql, params = connector.connections[-1].cursors[0].executed[0]
    assert "FROM products" in executed_sql
    assert params == {"customer_id": CUSTOMER_ID, "limit": 26}


def test_use_case_uses_max_rows_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_row(product_id=f"PRD-{i}") for i in range(4)])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_credit_cards_use_case({**ENV, "MAX_ROWS": "3"})
    assert use_case is not None
    result = use_case.execute(CUSTOMER_ID)

    assert len(result.cards) == 3
    assert result.truncated is True


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_list_credit_cards_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(DataSourceConnectionError("no route to host"), [])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_credit_cards_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(CUSTOMER_ID).cards == ()


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**ENV, "DB_ENGINE": "oracle"},
        {**ENV, "DB_ENGINE": "postgresql"},
        {"AWS_REGION": "us-east-1"},
        {"DSQL_CLUSTER_ENDPOINT": ENDPOINT},
        {**ENV, "DSQL_CLUSTER_ENDPOINT": f"https://{ENDPOINT}"},
    ],
)
def test_use_case_build_with_bad_configuration_returns_none(
    env: dict[str, str],
) -> None:
    assert build_list_credit_cards_use_case(env) is None


def test_build_clock_reads_as_of() -> None:
    assert build_clock({"AS_OF": "2026-03-14"}) == ClockSettings(
        as_of=datetime(2026, 3, 14, tzinfo=timezone.utc)
    )


def test_build_clock_without_as_of_uses_the_real_clock() -> None:
    assert build_clock({}) == ClockSettings(as_of=None)


def test_build_clock_with_a_bad_as_of_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for list_credit_cards" in caplog.text
