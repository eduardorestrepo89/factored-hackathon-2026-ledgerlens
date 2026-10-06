"""Tests for the classify_call_type Lambda handler."""

import importlib
import json
import logging
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from classify_call_type_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
)
from classify_call_type_lambda.application.use_cases.classify_call_type import (
    ClassifyCallTypeUseCase,
)
from classify_call_type_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from classify_call_type_lambda.delivery.settings import ClockSettings, DatabaseEngine
from classify_call_type_lambda.domain.errors import (
    CallReasonLookupError,
    DataSourceUnavailableError,
)

from .fakes import (
    AS_OF,
    AS_OF_SQL,
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeClassifyRepository,
    FakeConnector,
    FakeQueryProvider,
    Outcome,
    classify_responses,
    make_any_row,
)

pytestmark = pytest.mark.unit

EVENT = {"customer_id": CUSTOMER_ID}
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
CARD_REASONS = ["CARD_NOT_ACTIVE", "PAYMENT_OVERDUE", "CARD_EXPIRING"]
# Spec section 5: P07's flagged charge as the agent sees it.
P07_BODY = {
    "reasons": [
        {
            "reason": "FRAUD_SUSPECTED",
            "confidence": 0.77,
            "ref_id": TRANSACTION_ID,
            "evidence": {
                "transaction_date": "2026-05-31T06:09:15",
                "card_last4": "4497",
                "merchant_name": "Estación de Servicio",
                "amount": "288.69",
                "currency": "USD",
                "transaction_status": "Approved",
            },
        }
    ],
    "unavailable": [],
}


def make_context(
    tool_name: str = "classify-call-type-target___classify_call_type",
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
    import classify_call_type_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, Outcome] | None = None,
) -> FakeClassifyRepository:
    """Point the handler at a use case over a fake repository and a fixed clock."""
    database_repository = FakeClassifyRepository(
        classify_responses() if responses is None else responses
    )
    use_case = ClassifyCallTypeUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))
    return database_repository


def wire_connector(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any
) -> None:
    """Point the handler at real adapters over a fake connector and a fixed clock."""
    use_case = ClassifyCallTypeUseCase(
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


def reason_names(response: dict[str, Any]) -> list[str]:
    """Return the ranked reason names of a success response."""
    return [item["reason"] for item in body(response)["reasons"]]


def test_success_returns_gateway_content_with_the_reasons(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    response = module.handler(EVENT, make_context())

    assert body(response) == P07_BODY
    # ensure_ascii=False: accents reach the agent as they are.
    assert "Estación de Servicio" in text(response)
    # DEC-10: neither the score's name nor its value leaves the Lambda.
    assert "score" not in text(response)
    assert "62.00" not in text(response)


def test_success_over_real_adapters(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(module, monkeypatch, FakeConnector([make_any_row()]))

    response = module.handler(EVENT, make_context())

    assert reason_names(response) == [
        "FRAUD_SUSPECTED",
        "OPEN_CASE_FOLLOWUP",
        "FAILED_APP_ACTION",
    ]
    assert body(response)["unavailable"] == []


def test_bare_customer_id_and_as_of_reach_every_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    module.handler({"customer_id": " cli-ex6boaoefzhq "}, make_context())

    assert database_repository.queries == list(QUERY_NAMES)
    calls = database_repository.calls
    assert [params["customer_id"] for _name, params in calls] == [CUSTOMER_ID] * 4
    assert [params.get("as_of") for _name, params in calls] == [
        AS_OF_SQL,
        None,
        AS_OF_SQL,
        AS_OF_SQL,
    ]


def test_unknown_event_keys_are_ignored(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler({**EVENT, "as_of": "2020-01-01"}, make_context())

    assert "content" in response
    assert database_repository.calls[0][1]["as_of"] == AS_OF_SQL


def test_a_failed_source_comes_back_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(
        module,
        monkeypatch,
        classify_responses(call_reason_cards=QueryExecutionError("boom")),
    )

    response = module.handler(EVENT, make_context())

    assert reason_names(response) == ["FRAUD_SUSPECTED"]
    assert body(response)["unavailable"] == CARD_REASONS


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
        if name == "call_reason_transactions"
    ]
    assert sent == [datetime(2026, 6, 17, 23, 59, 59), datetime(2026, 6, 18, 8, 30)]


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "customer_id=CLI-EX6BOAOEFZHQ",
        {},
        {"customer_id": None},
        {"customer_id": ""},
        {"customer_id": "   "},
        {"customer_id": 42},
        {"customer_id": True},
        {"customer_id": ["CLI-EX6BOAOEFZHQ"]},
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
    ("error", "message"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError.MESSAGE),
        (QueryExecutionError("boom"), CallReasonLookupError.MESSAGE),
    ],
    ids=["unavailable", "lookup"],
)
def test_all_four_sources_failing_returns_its_message(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    message: str,
) -> None:
    database_repository = wire(
        module, monkeypatch, {name: error for name in QUERY_NAMES}
    )

    assert module.handler(EVENT, make_context()) == {"error": message}
    assert database_repository.queries == list(QUERY_NAMES)


def test_query_failure_over_real_adapters_returns_the_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "transactions" does not exist')
    wire_connector(module, monkeypatch, FakeConnector(error))

    response = module.handler(EVENT, make_context())

    assert response == {"error": CallReasonLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("session-target___get_session_context"),
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
    assert "classify_call_type" in response["error"]
    assert database_repository.calls == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    assert "content" in module.handler(EVENT, make_context("classify_call_type"))


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
        "Unexpected internal error ranking call reasons. "
        "Greet the customer and ask how you can help."
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


def test_success_log_names_the_reasons_but_no_customer_data(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire(
        module,
        monkeypatch,
        classify_responses(call_reason_cards=QueryExecutionError("boom")),
    )
    caplog.set_level(logging.INFO)

    module.handler(EVENT, make_context())

    assert (
        "classify_call_type returned reasons=['FRAUD_SUSPECTED'] "
        "(unavailable=['CARD_NOT_ACTIVE', 'PAYMENT_OVERDUE', 'CARD_EXPIRING'])"
    ) in caplog.text
    for private in (
        CUSTOMER_ID,
        TRANSACTION_ID,
        "Estación",
        "288.69",
        "0.77",
        "62.00",
    ):
        assert private not in caplog.text
