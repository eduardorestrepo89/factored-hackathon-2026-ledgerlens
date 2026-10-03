"""Tests for the open_claim Lambda handler."""

import importlib
import json
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from open_claim_lambda.application.use_cases.open_claim import OpenClaimUseCase
from open_claim_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from open_claim_lambda.delivery.settings import ClockSettings, DatabaseEngine
from open_claim_lambda.domain.errors import (
    ClaimError,
    DataSourceUnavailableError,
    TransactionsNotFoundError,
)

from .fakes import CUSTOMER_ID, FakeConnector, make_row

pytestmark = pytest.mark.unit

EVENT = {
    "customer_id": CUSTOMER_ID,
    "transaction_ids": ["TRX-1"],
    "claim_type": "fraud",
    "customer_statement": "No reconozco este cargo",
    "customer_confirmed": True,
}
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
INSERTED = [{"complaint_id": "CMP-X"}]
ESTIMATE = [{"median_days": 4.2, "p90_days": 11.5}]
NOT_CONFIRMED = (
    "Invalid value for 'customer_confirmed': must be true, after the customer "
    "explicitly confirmed these transactions. Ask the customer to confirm and retry."
)


def make_context(tool_name: str = "open-claim-target___open_claim") -> SimpleNamespace:
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
    import open_claim_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any) -> None:
    """Point the handler at real adapters over a fake connector, with AS_OF set."""
    use_case = OpenClaimUseCase(
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


def test_success_opens_the_claim_and_returns_the_estimate(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector(([make_row()], INSERTED, ESTIMATE))
    wire(module, monkeypatch, connector)

    payload = body(module.handler(EVENT, make_context()))

    claim = payload["claims"][0]
    assert claim["card_last4"] == "4821"
    assert claim["transaction_ids"] == ["TRX-1"]
    assert claim["claimed_amount"] == "740.00"
    assert claim["priority"] == "High"
    assert claim["already_existed"] is False
    assert claim["claim_id"].startswith("CMP-")
    assert payload["resolution_estimate"] == {"median_days": 5, "p90_days": 12}
    insert_params = connector.connections[-1].cursors[1].executed[0][1]
    assert insert_params["creation_date"] == datetime(2026, 6, 17, 23, 59, 59)


def test_a_duplicate_insert_reports_the_existing_claim(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    duplicate = psycopg.errors.UniqueViolation("duplicate key value")
    wire(module, monkeypatch, FakeConnector(([make_row()], duplicate, ESTIMATE)))

    payload = body(module.handler(EVENT, make_context()))

    assert payload["claims"][0]["already_existed"] is True


def test_a_failing_estimate_still_returns_the_open_claims(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsupported = psycopg.errors.UndefinedFunction(
        "function percentile_cont does not exist"
    )
    wire(module, monkeypatch, FakeConnector(([make_row()], INSERTED, unsupported)))

    payload = body(module.handler(EVENT, make_context()))

    assert len(payload["claims"]) == 1
    assert payload["resolution_estimate"] is None


@pytest.mark.parametrize("confirmed", [False, None, "true"])
def test_an_unconfirmed_claim_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, confirmed: object
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler(
        {**EVENT, "customer_confirmed": confirmed}, make_context()
    )

    assert response == {"error": NOT_CONFIRMED}
    assert connector.connections == []


def test_unknown_transactions_return_the_not_found_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    response = module.handler(EVENT, make_context())

    assert response == {"error": TransactionsNotFoundError(["TRX-1"]).message}


def test_a_failing_insert_returns_the_claim_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.InsufficientPrivilege("permission denied for complaints")
    wire(module, monkeypatch, FakeConnector(([make_row()], error)))

    assert module.handler(EVENT, make_context()) == {"error": ClaimError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [make_context("block-credit-card-target___block_credit_card"), None],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    connector = FakeConnector()
    wire(module, monkeypatch, connector)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "open_claim" in response["error"]
    assert connector.connections == []


def test_unexpected_exception_returns_a_generic_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: object) -> None:
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error opening the claim. "
        "Offer a hand-off to a human agent."
    )


def test_missing_configuration_or_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert module.USE_CASE is None
    assert module.handler(EVENT, make_context()) == {
        "error": DataSourceUnavailableError.MESSAGE
    }

    wire(module, monkeypatch, FakeConnector([make_row()]))
    monkeypatch.setattr(module, "CLOCK", None)
    assert module.handler(EVENT, make_context()) == {
        "error": DataSourceUnavailableError.MESSAGE
    }
