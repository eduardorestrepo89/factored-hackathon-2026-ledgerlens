"""Tests for the list_card_transactions Lambda handler."""

import importlib
import json
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from ledgerlens.application.ports.errors import DataSourceConnectionError
from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from ledgerlens.delivery.settings import DatabaseEngine
from ledgerlens.domain.errors import DataSourceUnavailableError
from ledgerlens_fakes import FakeConnector, make_row

pytestmark = pytest.mark.unit

EVENT = {"customer_id": "CUST-1", "date_from": "2026-09-01", "date_to": "2026-09-29"}


def make_context(
    tool_name: str = "list-card-transactions-target___list_card_transactions",
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
    ):
        monkeypatch.delenv(name, raising=False)
    import ledgerlens.delivery.list_card_transactions_handler as handler_module

    return importlib.reload(handler_module)


def wire(module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any) -> None:
    """Point the handler's global use case at real adapters over a fake connector."""
    use_case = ListCardTransactionsUseCase(
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


def test_success_returns_gateway_content_with_the_transactions(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([make_row()]))

    response = module.handler(EVENT, make_context())

    payload = body(response)
    assert payload["count"] == 1
    assert payload["truncated"] is False
    assert payload["transactions"][0]["amount"] == "12.50"
    assert payload["transactions"][0]["transaction_date"] == "2026-09-20T14:30:00+00:00"


def test_non_ascii_text_is_not_escaped(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([make_row()]))

    response = module.handler(EVENT, make_context())

    assert "Óptica Visión" in response["content"][0]["text"]


def test_empty_result_is_a_success(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    assert body(module.handler(EVENT, make_context()))["count"] == 0


def test_invalid_input_returns_the_domain_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler({**EVENT, "card_last4": "12"}, make_context())

    assert response == {
        "error": "Invalid value for 'card_last4': must be exactly 4 digits. "
        "Ask the customer to confirm and retry."
    }
    assert connector.connections == []


@pytest.mark.parametrize("event", [None, [], "customer_id=CUST-1"])
def test_non_object_event_returns_a_clean_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    wire(module, monkeypatch, FakeConnector())

    response = module.handler(event, make_context())

    assert "must be a JSON object" in response["error"]


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
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
    assert "list_card_transactions" in response["error"]
    assert connector.connections == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    assert "content" in module.handler(EVENT, make_context("list_card_transactions"))


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
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
