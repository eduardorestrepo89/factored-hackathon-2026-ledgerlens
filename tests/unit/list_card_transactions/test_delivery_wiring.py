"""Tests for dependency wiring and the card transactions presenter."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import list_card_transactions_lambda.utils.connectors.dsql as dsql_module
import pytest
from list_card_transactions_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from list_card_transactions_lambda.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from list_card_transactions_lambda.delivery.dependencies import dependencies_builder
from list_card_transactions_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_list_card_transactions_use_case,
    build_query_provider,
    build_settings,
)
from list_card_transactions_lambda.delivery.presenters.card_transactions import (
    present_card_transactions,
)
from list_card_transactions_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from list_card_transactions_lambda.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)
from list_card_transactions_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from list_card_transactions_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import FakeConnector, make_filters, make_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
SETTINGS = DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL, max_rows=25)


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_dsql_settings_reads_the_environment() -> None:
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ledgerlens_readonly"
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
    assert "DISTINCT ON" in provider.get("list_card_transactions")


def test_every_engine_has_a_dialect_folder_with_the_sql() -> None:
    for engine in DatabaseEngine:
        sql_file = QUERIES_ROOT / SQL_DIALECTS[engine] / "list_card_transactions.sql"
        assert sql_file.is_file()


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

    use_case = build_list_card_transactions_use_case(ENV)
    assert isinstance(use_case, ListCardTransactionsUseCase)
    result = use_case.execute(make_filters())

    assert result.transactions[0].transaction_id == "TX-1"
    executed_sql, params = connector.connections[-1].cursors[0].executed[0]
    assert "FROM transactions" in executed_sql
    assert params["limit"] == 26


def test_use_case_uses_max_rows_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_row(transaction_id=str(i)) for i in range(4)])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_card_transactions_use_case({**ENV, "MAX_ROWS": "3"})
    assert use_case is not None
    result = use_case.execute(make_filters())

    assert len(result.transactions) == 3
    assert result.truncated is True


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_list_card_transactions_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(DataSourceConnectionError("no route to host"), [])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_card_transactions_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(make_filters()).transactions == ()


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
    assert build_list_card_transactions_use_case(env) is None


def make_transaction(**overrides: object) -> CardTransaction:
    """Build a CardTransaction for presenter tests."""
    values: dict[str, object] = {
        "transaction_id": "TX-1",
        "transaction_date": datetime(
            2026, 9, 20, 14, 30, tzinfo=timezone(timedelta(hours=-5))
        ),
        "card_last4": "4242",
        "amount": Decimal("12.5"),
        "currency": "COP",
        "transaction_status": "Approved",
        "merchant_name": "Óptica Visión",
        "merchant_category": "Health",
        "channel": "POS",
        "transaction_city": "Medellín",
        "transaction_country": "Colombia",
    }
    values.update(overrides)
    return CardTransaction(**values)  # type: ignore[arg-type]


def test_presenter_shapes_the_agent_json() -> None:
    result = CardTransactionsResult(transactions=(make_transaction(),), truncated=True)

    assert present_card_transactions(result) == {
        "transactions": [
            {
                "transaction_id": "TX-1",
                "transaction_date": "2026-09-20T14:30:00-05:00",
                "card_last4": "4242",
                "merchant_name": "Óptica Visión",
                "merchant_category": "Health",
                "amount": "12.50",
                "currency": "COP",
                "channel": "POS",
                "transaction_city": "Medellín",
                "transaction_country": "Colombia",
                "transaction_status": "Approved",
            }
        ],
        "count": 1,
        "truncated": True,
    }


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("7"), "7.00"),
        (Decimal("10.005"), "10.01"),
        (Decimal("0.004"), "0.00"),
        (Decimal("412000.38"), "412000.38"),
    ],
)
def test_presenter_formats_amounts_as_two_decimal_strings(
    amount: Decimal, expected: str
) -> None:
    result = CardTransactionsResult((make_transaction(amount=amount),), False)

    assert present_card_transactions(result)["transactions"][0]["amount"] == expected


def test_presenter_keeps_nulls_and_output_is_json_serialisable() -> None:
    transaction = make_transaction(currency=None, merchant_name=None)
    body = present_card_transactions(CardTransactionsResult((transaction,), False))

    assert body["transactions"][0]["currency"] is None
    assert body["transactions"][0]["merchant_name"] is None
    json.dumps(body)


def test_presenter_handles_an_empty_result() -> None:
    assert present_card_transactions(CardTransactionsResult((), False)) == {
        "transactions": [],
        "count": 0,
        "truncated": False,
    }


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
    assert "Invalid AS_OF for list_card_transactions" in caplog.text
