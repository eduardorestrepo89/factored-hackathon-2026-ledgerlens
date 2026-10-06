"""Tests for the explain_transaction Lambda handler."""

import importlib
import json
import logging
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from explain_transaction_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
)
from explain_transaction_lambda.application.use_cases.explain_transaction import (
    ExplainTransactionUseCase,
)
from explain_transaction_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from explain_transaction_lambda.delivery.settings import ClockSettings, DatabaseEngine
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    ExplainDataIntegrityError,
    ExplainLookupError,
    TransactionNotFoundError,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeConnector,
    FakeExplainRepository,
    FakeQueryProvider,
    Outcome,
    explain_responses,
    make_any_row,
    make_core_row,
)

pytestmark = pytest.mark.unit

EVENT = {"customer_id": CUSTOMER_ID, "transaction_id": TRANSACTION_ID}
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
INVALID_TRANSACTION_ID = (
    "Invalid value for 'transaction_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
OUTPUT_KEYS = ["transaction", "fx", "decline", "habit", "app_activity", "unavailable"]


def make_context(
    tool_name: str = "explain-transaction-target___explain_transaction",
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
    import explain_transaction_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, Outcome] | None = None,
) -> FakeExplainRepository:
    """Point the handler at a use case over a fake repository and a fixed clock."""
    database_repository = FakeExplainRepository(
        explain_responses() if responses is None else responses
    )
    use_case = ExplainTransactionUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))
    return database_repository


def wire_connector(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any
) -> None:
    """Point the handler at real adapters over a fake connector and a fixed clock."""
    use_case = ExplainTransactionUseCase(
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))


def text(response: dict[str, Any]) -> str:
    """Return the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return content[0]["text"]


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    return json.loads(text(response))


def test_success_returns_gateway_content_with_the_explanation(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    response = module.handler(EVENT, make_context())
    payload = body(response)

    assert list(payload) == OUTPUT_KEYS
    assert payload["transaction"]["transaction_id"] == TRANSACTION_ID
    assert payload["transaction"]["amount"] == "288.69"
    assert payload["fx"] is None
    assert payload["decline"] is None
    assert payload["habit"]["history_count"] == 1
    assert payload["app_activity"] == {"found": False}
    assert payload["unavailable"] == []
    # ensure_ascii=False: accents reach the agent as they are.
    assert "Estación de Servicio" in text(response)


def test_success_over_real_adapters(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(module, monkeypatch, FakeConnector([make_any_row()]))

    payload = body(module.handler(EVENT, make_context()))

    assert payload["transaction"]["transaction_id"] == TRANSACTION_ID
    assert payload["app_activity"]["found"] is True
    assert payload["unavailable"] == []


def test_both_ids_and_now_reach_the_use_case(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    module.handler(
        {
            "customer_id": " cli-ex6boaoefzhq ",
            "transaction_id": " trx-23bijau4gl46atpw9sty ",
        },
        make_context(),
    )

    assert database_repository.queries == list(QUERY_NAMES)
    assert database_repository.calls[0][1] == {
        "customer_id": CUSTOMER_ID,
        "transaction_id": TRANSACTION_ID,
        "as_of": AS_OF_SQL,
    }


def test_unknown_event_keys_are_ignored(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler({**EVENT, "as_of": "2020-01-01"}, make_context())

    assert "content" in response
    assert database_repository.calls[0][1]["as_of"] == AS_OF_SQL


def test_a_failed_section_comes_back_null_and_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(
        module,
        monkeypatch,
        explain_responses(
            transaction_habit=QueryExecutionError(
                "function percentile_cont is not supported"
            )
        ),
    )

    payload = body(module.handler(EVENT, make_context()))

    assert payload["habit"] is None
    assert payload["unavailable"] == ["habit"]
    assert payload["app_activity"] == {"found": False}


def test_now_is_read_on_every_call(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)
    times = iter(
        [
            datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc),
            datetime(2026, 6, 18, 8, 30, tzinfo=timezone.utc),
        ]
    )
    monkeypatch.setattr(module, "CLOCK", SimpleNamespace(now=lambda: next(times)))

    module.handler(EVENT, make_context())
    module.handler(EVENT, make_context())

    sent = [
        params["as_of"]
        for name, params in database_repository.calls
        if name == "explain_transaction"
    ]
    assert sent == [datetime(2026, 6, 17, 23, 59, 59), datetime(2026, 6, 18, 8, 30)]


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "customer_id=CLI-EX6BOAOEFZHQ",
        {},
        {"transaction_id": TRANSACTION_ID},
        {"customer_id": None, "transaction_id": TRANSACTION_ID},
        {"customer_id": "", "transaction_id": TRANSACTION_ID},
        {"customer_id": "   ", "transaction_id": TRANSACTION_ID},
        {"customer_id": 42, "transaction_id": TRANSACTION_ID},
        {"customer_id": True, "transaction_id": TRANSACTION_ID},
    ],
)
def test_invalid_customer_id_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler(event, make_context())

    assert response == {"error": INVALID_CUSTOMER_ID}
    assert database_repository.calls == []


@pytest.mark.parametrize(
    "transaction_id", [None, "", "   ", 42, True, ["TRX-23BIJAU4GL46ATPW9STY"]]
)
def test_invalid_transaction_id_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, transaction_id: object
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler(
        {"customer_id": CUSTOMER_ID, "transaction_id": transaction_id},
        make_context(),
    )

    assert response == {"error": INVALID_TRANSACTION_ID}
    assert database_repository.calls == []


def test_a_missing_transaction_id_returns_the_input_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler({"customer_id": CUSTOMER_ID}, make_context())

    assert response == {"error": INVALID_TRANSACTION_ID}
    assert database_repository.calls == []


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError.MESSAGE),
        (QueryExecutionError("boom"), ExplainLookupError.MESSAGE),
        ([], TransactionNotFoundError.MESSAGE),
        ([make_core_row(transaction_id=None)], ExplainDataIntegrityError.MESSAGE),
    ],
    ids=["unavailable", "lookup", "not-found", "integrity"],
)
def test_a_core_failure_returns_its_message(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    outcome: Outcome,
    message: str,
) -> None:
    database_repository = wire(
        module, monkeypatch, explain_responses(explain_transaction=outcome)
    )

    assert module.handler(EVENT, make_context()) == {"error": message}
    assert database_repository.queries == ["explain_transaction"]


def test_query_failure_over_real_adapters_returns_the_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "transactions" does not exist')
    wire_connector(module, monkeypatch, FakeConnector(error))

    response = module.handler(EVENT, make_context())

    assert response == {"error": ExplainLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("fraud-target___transaction_fraud_detection"),
        None,
        SimpleNamespace(client_context=None),
        SimpleNamespace(client_context=SimpleNamespace(custom={})),
        SimpleNamespace(client_context=SimpleNamespace(custom=None)),
        make_context(42),  # type: ignore[arg-type]
    ],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "explain_transaction" in response["error"]
    assert database_repository.calls == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    assert "content" in module.handler(EVENT, make_context("explain_transaction"))


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error explaining the charge. "
        "Offer a hand-off to a human agent."
    )
    assert "hunter2" not in response["error"]


def test_missing_configuration_returns_data_source_unavailable(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)
    monkeypatch.setattr(module, "CLOCK", None)

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}
    assert database_repository.calls == []


def test_default_environment_uses_the_real_clock(module: ModuleType) -> None:
    assert module.CLOCK == ClockSettings(as_of=None)


def test_a_bad_as_of_env_var_leaves_the_clock_unset(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AS_OF", "yesterday")

    assert importlib.reload(module).CLOCK is None


def test_cold_start_failure_then_failed_retry_returns_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(
        module, monkeypatch, FakeConnector(DataSourceConnectionError("down"))
    )

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_success_log_names_unavailable_but_no_customer_data(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire(
        module,
        monkeypatch,
        explain_responses(transaction_habit=QueryExecutionError("boom")),
    )
    caplog.set_level(logging.INFO)

    module.handler(EVENT, make_context())

    assert (
        "explain_transaction returned explanation (unavailable=['habit'])"
        in caplog.text
    )
    for private in (
        CUSTOMER_ID,
        TRANSACTION_ID,
        "Estación",
        "288.69",
        "Ciudad de México",
    ):
        assert private not in caplog.text
