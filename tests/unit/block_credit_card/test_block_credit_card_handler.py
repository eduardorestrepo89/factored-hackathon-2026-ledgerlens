"""Tests for the block_credit_card Lambda handler."""

import importlib
import json
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from block_credit_card_lambda.delivery.settings import ClockSettings, DatabaseEngine
from block_credit_card_lambda.domain.errors import (
    CardNotFoundError,
    CardUpdateError,
    DataSourceUnavailableError,
)

from .fakes import CUSTOMER_ID, FakeConnector, make_row

pytestmark = pytest.mark.unit

EVENT = {
    "customer_id": CUSTOMER_ID,
    "card_last4": "4821",
    "reason": "suspected_fraud",
    "customer_confirmed": True,
}
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
BLOCKED = [{"product_id": "PRD-1"}]
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
NOT_CONFIRMED = (
    "Invalid value for 'customer_confirmed': must be true, after the customer "
    "explicitly confirmed the block. Ask the customer to confirm and retry."
)


def make_context(
    tool_name: str = "block-credit-card-target___block_credit_card",
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
        "DSQL_CLUSTER_ENDPOINT",
        "DSQL_DB_USER",
        "AWS_REGION",
        "AS_OF",
    ):
        monkeypatch.delenv(name, raising=False)
    import block_credit_card_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any) -> None:
    """Point the handler at real adapters over a fake connector, with AS_OF set."""
    use_case = BlockCreditCardUseCase(
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def executed(connector: FakeConnector) -> list[tuple[str, Any]]:
    """Return (sql, params) of every statement on the last connection."""
    return [cursor.executed[0] for cursor in connector.connections[-1].cursors]


def test_success_blocks_the_card_with_the_clocks_now(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector(([make_row()], BLOCKED))
    wire(module, monkeypatch, connector)

    payload = body(module.handler(EVENT, make_context()))

    assert payload == {
        "card_last4": "4821",
        "status": "Blocked",
        "already_blocked": False,
    }
    (_, find_params), (block_sql, block_params) = executed(connector)
    assert find_params == {"customer_id": CUSTOMER_ID, "card_last4": "4821"}
    assert "UPDATE products" in block_sql
    assert block_params == {
        "customer_id": CUSTOMER_ID,
        "product_id": "PRD-1",
        "last_updated": datetime(2026, 6, 17, 23, 59, 59),
    }


def test_an_already_blocked_card_is_reported_without_an_update(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row(product_status="Blocked")])
    wire(module, monkeypatch, connector)

    assert body(module.handler(EVENT, make_context()))["already_blocked"] is True
    assert len(executed(connector)) == 1


@pytest.mark.parametrize("confirmed", [False, None, "true", 1])
def test_an_unconfirmed_block_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, confirmed: object
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler(
        {**EVENT, "customer_confirmed": confirmed}, make_context()
    )

    assert response == {"error": NOT_CONFIRMED}
    assert connector.connections == []


def test_a_missing_confirmation_returns_the_input_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)
    event = {k: v for k, v in EVENT.items() if k != "customer_confirmed"}

    assert module.handler(event, make_context()) == {"error": NOT_CONFIRMED}
    assert connector.connections == []


@pytest.mark.parametrize("event", [None, [], "block 4821"])
def test_a_non_object_event_returns_the_customer_id_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    assert module.handler(event, make_context()) == {"error": INVALID_CUSTOMER_ID}
    assert connector.connections == []


def test_an_unknown_card_returns_the_not_found_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    response = module.handler(EVENT, make_context())

    assert response == {"error": CardNotFoundError("4821").message}


def test_a_query_failure_returns_the_card_update_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "products" does not exist')
    wire(module, monkeypatch, FakeConnector(error))

    assert module.handler(EVENT, make_context()) == {"error": CardUpdateError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("list-credit-cards-target___list_credit_cards"),
        None,
        SimpleNamespace(client_context=None),
        SimpleNamespace(client_context=SimpleNamespace(custom={})),
    ],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    connector = FakeConnector()
    wire(module, monkeypatch, connector)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "block_credit_card" in response["error"]
    assert connector.connections == []


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error blocking the card. "
        "Offer an urgent hand-off to a human agent."
    )


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


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)
    monkeypatch.setattr(module, "CLOCK", None)

    assert module.handler(EVENT, make_context()) == {
        "error": DataSourceUnavailableError.MESSAGE
    }
    assert connector.connections == []
