"""Tests for settings, dependency wiring and the card transactions presenter."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from ledgerlens.application.ports.errors import DataSourceConnectionError
from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.delivery.dependencies import dependencies_builder
from ledgerlens.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    build_connector,
    build_database_repository,
    build_list_card_transactions_use_case,
    build_query_provider,
    build_settings,
)
from ledgerlens.delivery.presenters.card_transactions import (
    present_card_transactions,
)
from ledgerlens.delivery.settings import ConfigurationError, DatabaseSettings
from ledgerlens.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)
from ledgerlens.infrastructure.repositories.postgresql_repository import (
    PostgreSQLRepository,
)
from ledgerlens.utils.connectors.aurora_postgresql import AuroraPostgreSQLConnector
from ledgerlens_fakes import FakeConnector, make_filters, make_row

pytestmark = pytest.mark.unit

ENV = {"DB_ENGINE": "postgresql", "DB_SECRET_ARN": "arn:aws:secretsmanager:x"}
SETTINGS = DatabaseSettings(
    engine="postgresql",
    secret_arn="arn:aws:secretsmanager:x",
    statement_timeout_ms=5000,
    max_rows=25,
)


def test_settings_apply_defaults() -> None:
    assert DatabaseSettings.from_env(ENV) == SETTINGS


def test_settings_read_overrides_and_normalise_engine() -> None:
    env = {
        **ENV,
        "DB_ENGINE": " PostgreSQL ",
        "DB_STATEMENT_TIMEOUT_MS": "8000",
        "MAX_ROWS": "10",
    }

    settings = DatabaseSettings.from_env(env)

    assert (settings.engine, settings.statement_timeout_ms, settings.max_rows) == (
        "postgresql",
        8000,
        10,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DB_ENGINE": ""}, "DB_ENGINE"),
        ({"DB_ENGINE": "mysql"}, "DB_ENGINE"),
        ({"DB_SECRET_ARN": "  "}, "DB_SECRET_ARN"),
        ({"DB_STATEMENT_TIMEOUT_MS": "abc"}, "DB_STATEMENT_TIMEOUT_MS"),
        ({"DB_STATEMENT_TIMEOUT_MS": "0"}, "DB_STATEMENT_TIMEOUT_MS"),
        ({"MAX_ROWS": "-5"}, "MAX_ROWS"),
    ],
)
def test_invalid_settings_raise_configuration_error(
    overrides: dict[str, str], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        DatabaseSettings.from_env({**ENV, **overrides})


def test_missing_variables_raise_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="DB_ENGINE"):
        DatabaseSettings.from_env({})


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_connector_does_not_connect() -> None:
    connector = build_connector(SETTINGS)

    assert isinstance(connector, AuroraPostgreSQLConnector)


def test_query_provider_is_cached_per_engine_and_finds_the_sql() -> None:
    provider = build_query_provider("postgresql")

    assert provider is build_query_provider("postgresql")
    assert "DISTINCT ON" in provider.get("list_card_transactions")
    assert (QUERIES_ROOT / "postgresql" / "list_card_transactions.sql").is_file()


def test_build_database_repository_wraps_the_connector_for_the_engine() -> None:
    database_repository = build_database_repository("postgresql", FakeConnector())

    assert isinstance(database_repository, PostgreSQLRepository)


def test_build_database_repository_rejects_an_unknown_engine() -> None:
    with pytest.raises(ConfigurationError):
        build_database_repository("oracle", FakeConnector())


def use_fake_connector(
    monkeypatch: pytest.MonkeyPatch, connector: FakeConnector
) -> None:
    """Make the builder hand out ``connector`` instead of a real Aurora one."""
    monkeypatch.setattr(dependencies_builder, "build_connector", lambda _s: connector)


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
    "env", [{}, {"DB_ENGINE": "oracle"}, {"DB_ENGINE": "postgresql"}]
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
