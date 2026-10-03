"""Tests for the list_credit_cards Lambda handler."""

import importlib
import json
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from list_credit_cards_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from list_credit_cards_lambda.application.use_cases.list_credit_cards import (
    ListCreditCardsUseCase,
)
from list_credit_cards_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from list_credit_cards_lambda.delivery.settings import ClockSettings, DatabaseEngine
from list_credit_cards_lambda.domain.errors import (
    CardLookupError,
    DataSourceUnavailableError,
)

from .fakes import CUSTOMER_ID, FakeConnector, make_row

pytestmark = pytest.mark.unit

EVENT = {"customer_id": CUSTOMER_ID}
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)


def make_context(
    tool_name: str = "list-credit-cards-target___list_credit_cards",
) -> SimpleNamespace:
    """Build a Lambda context carrying the Gateway tool name."""
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the handler module fresh, with no DB env vars (no AWS calls)."""
    for name in (
        "DB_ENGINE",
        "MAX_ROWS",
        "DSQL_CLUSTER_ENDPOINT",
        "DSQL_DB_USER",
        "AWS_REGION",
        "AS_OF",
    ):
        monkeypatch.delenv(name, raising=False)
    import list_credit_cards_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any) -> None:
    """Point the handler's global use case at real adapters over a fake connector."""
    use_case = ListCreditCardsUseCase(
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
        max_rows=25,
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def sent_params(connector: FakeConnector) -> Any:
    """Return the params of the first query the connector executed."""
    return connector.connections[-1].cursors[0].executed[0][1]


def test_success_returns_gateway_content_with_the_cards(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([make_row()]))

    payload = body(module.handler(EVENT, make_context()))

    assert payload["count"] == 1
    assert payload["truncated"] is False
    assert payload["cards"][0] == {
        "card_last4": "4821",
        "product_status": "Active",
        "currency": "COP",
        "current_balance": "1250000.00",
        "credit_limit": "3000000.00",
        "available_credit": "1750000.00",
        "expiration_date": "2027-03-31",
        "days_past_due": 0,
    }


def test_bare_customer_id_is_cleaned_before_the_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    module.handler({"customer_id": "  cli-itiecue8prh9 "}, make_context())

    assert sent_params(connector) == {"customer_id": "CLI-ITIECUE8PRH9", "limit": 26}


def test_unknown_event_keys_are_ignored(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler({**EVENT, "status": "Blocked"}, make_context())

    assert "content" in response
    assert sent_params(connector) == {"customer_id": CUSTOMER_ID, "limit": 26}


def test_no_cards_returns_null_cards(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    assert body(module.handler(EVENT, make_context())) == {
        "cards": None,
        "count": 0,
        "truncated": False,
    }


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "customer_id=CLI-ITIECUE8PRH9",
        {},
        {"customer_id": None},
        {"customer_id": ""},
        {"customer_id": "   "},
        {"customer_id": 42},
        {"customer_id": True},
    ],
)
def test_invalid_customer_id_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler(event, make_context())

    assert response == {"error": INVALID_CUSTOMER_ID}
    assert connector.connections == []


def test_query_failure_returns_the_card_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "products" does not exist')
    wire(module, monkeypatch, FakeConnector(error))

    response = module.handler(EVENT, make_context())

    assert response == {"error": CardLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("list-card-transactions-target___list_card_transactions"),
        None,
        SimpleNamespace(client_context=None),
        SimpleNamespace(client_context=SimpleNamespace(custom={})),
        SimpleNamespace(client_context=SimpleNamespace(custom=None)),
    ],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    connector = FakeConnector()
    wire(module, monkeypatch, connector)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "list_credit_cards" in response["error"]
    assert connector.connections == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    assert "content" in module.handler(EVENT, make_context("list_credit_cards"))


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error listing credit cards. "
        "Offer a hand-off to a human agent."
    )
    assert "hunter2" not in response["error"]


def test_missing_configuration_returns_data_source_unavailable(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_cold_start_failure_then_failed_retry_returns_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector(DataSourceConnectionError("down")))

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_default_environment_uses_the_real_clock(module: ModuleType) -> None:
    assert module.CLOCK == ClockSettings(as_of=None)


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)
    monkeypatch.setattr(module, "CLOCK", None)

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}
    assert connector.connections == []


def test_a_bad_as_of_env_var_leaves_the_clock_unset(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AS_OF", "yesterday")

    assert importlib.reload(module).CLOCK is None
