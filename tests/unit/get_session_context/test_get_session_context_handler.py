"""Tests for the get_session_context Lambda handler."""

import importlib
import json
import logging
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from get_session_context_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
)
from get_session_context_lambda.application.use_cases.get_session_context import (
    GetSessionContextUseCase,
)
from get_session_context_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from get_session_context_lambda.delivery.settings import ClockSettings, DatabaseEngine
from get_session_context_lambda.domain.errors import (
    CustomerNotFoundError,
    DataSourceUnavailableError,
    SessionContextDataIntegrityError,
    SessionContextLookupError,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeConnector,
    FakeQueryProvider,
    FakeSessionRepository,
    Outcome,
    make_any_section_row,
    make_profile_row,
    session_responses,
)

pytestmark = pytest.mark.unit

EVENT = {"customer_id": CUSTOMER_ID}
AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 3, 14, 12, 0)
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
OUTPUT_KEYS = [
    "as_of",
    "customer",
    "cards",
    "recent_transactions",
    "digital_signals",
    "open_cases",
    "truncated",
    "unavailable",
]


def make_context(
    tool_name: str = "get-session-context-target___get_session_context",
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
    import get_session_context_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, Outcome] | None = None,
) -> FakeSessionRepository:
    """Point the handler at a use case over a fake repository and a fixed clock."""
    database_repository = FakeSessionRepository(
        session_responses() if responses is None else responses
    )
    use_case = GetSessionContextUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))
    return database_repository


def wire_connector(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any
) -> None:
    """Point the handler at real adapters over a fake connector and a fixed clock."""
    use_case = GetSessionContextUseCase(
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


def test_success_returns_gateway_content_with_the_snapshot(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    payload = body(module.handler(EVENT, make_context()))

    assert list(payload) == OUTPUT_KEYS
    assert payload["as_of"] == "2026-03-14T12:00:00Z"
    assert payload["customer"]["customer_id"] == CUSTOMER_ID
    assert payload["customer"]["city"] == "Bogotá"
    assert payload["cards"][0]["available_credit"] == "1750000.00"
    assert payload["recent_transactions"][0]["flags"] == [
        "declined",
        "above_usual_amount",
    ]
    assert payload["digital_signals"][0]["signal"] == "FAILED_ACTION"
    assert payload["open_cases"][0]["days_open"] == 3
    assert payload["truncated"] == []
    assert payload["unavailable"] == []


def test_success_over_real_adapters(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(module, monkeypatch, FakeConnector([make_any_section_row()]))

    payload = body(module.handler(EVENT, make_context()))

    assert payload["customer"]["customer_id"] == CUSTOMER_ID
    assert payload["unavailable"] == []


def test_bare_customer_id_and_as_of_reach_every_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    module.handler({"customer_id": "  cli-itiecue8prh9 "}, make_context())

    assert database_repository.queries == list(QUERY_NAMES)
    for name, params in database_repository.calls:
        assert params["customer_id"] == CUSTOMER_ID, name
        if "as_of" in params:
            assert params["as_of"] == AS_OF_SQL, name


def test_unknown_event_keys_are_ignored(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler({**EVENT, "as_of": "2020-01-01"}, make_context())

    assert body(response)["as_of"] == "2026-03-14T12:00:00Z"
    assert database_repository.queries == list(QUERY_NAMES)


def test_a_failed_section_comes_back_null_and_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(
        module,
        monkeypatch,
        session_responses(
            session_recent_transactions=QueryExecutionError(
                "function percentile_cont is not supported"
            )
        ),
    )

    payload = body(module.handler(EVENT, make_context()))

    assert payload["recent_transactions"] is None
    assert payload["unavailable"] == ["recent_transactions"]
    assert payload["cards"] is not None
    assert payload["digital_signals"] is not None
    assert payload["open_cases"] is not None


def test_now_is_read_on_every_call(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)
    times = iter(
        [
            datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 15, 8, 30, tzinfo=timezone.utc),
        ]
    )
    monkeypatch.setattr(module, "CLOCK", SimpleNamespace(now=lambda: next(times)))

    first = body(module.handler(EVENT, make_context()))
    second = body(module.handler(EVENT, make_context()))

    assert first["as_of"] == "2026-03-14T12:00:00Z"
    assert second["as_of"] == "2026-03-15T08:30:00Z"
    sent = [
        params["as_of"]
        for _name, params in database_repository.calls
        if "as_of" in params
    ]
    assert sent[0] == datetime(2026, 3, 14, 12, 0)
    assert sent[-1] == datetime(2026, 3, 15, 8, 30)


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
    database_repository = wire(module, monkeypatch)

    response = module.handler(event, make_context())

    assert response == {"error": INVALID_CUSTOMER_ID}
    assert database_repository.calls == []


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError.MESSAGE),
        (QueryExecutionError("boom"), SessionContextLookupError.MESSAGE),
        ([], CustomerNotFoundError.MESSAGE),
        (
            [make_profile_row(customer_id=None)],
            SessionContextDataIntegrityError.MESSAGE,
        ),
    ],
    ids=["unavailable", "lookup", "not-found", "integrity"],
)
def test_a_customer_section_failure_returns_its_message(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    outcome: Outcome,
    message: str,
) -> None:
    wire(module, monkeypatch, session_responses(session_customer_profile=outcome))

    assert module.handler(EVENT, make_context()) == {"error": message}


def test_query_failure_over_real_adapters_returns_the_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "customers" does not exist')
    wire_connector(module, monkeypatch, FakeConnector(error))

    response = module.handler(EVENT, make_context())

    assert response == {"error": SessionContextLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("list-credit-cards-target___list_credit_cards"),
        None,
        SimpleNamespace(client_context=None),
        SimpleNamespace(client_context=SimpleNamespace(custom={})),
        SimpleNamespace(client_context=SimpleNamespace(custom=None)),
    ],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "get_session_context" in response["error"]
    assert database_repository.calls == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    assert "content" in module.handler(EVENT, make_context("get_session_context"))


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error loading the customer's context. "
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


def test_success_log_names_the_lists_but_no_customer_data(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire(
        module,
        monkeypatch,
        session_responses(session_open_cases=QueryExecutionError("boom")),
    )
    caplog.set_level(logging.INFO)

    module.handler(EVENT, make_context())

    assert (
        "get_session_context returned context "
        "(unavailable=['open_cases'], truncated=[])"
    ) in caplog.text
    assert "Ana" not in caplog.text
    assert "Bogot" not in caplog.text
