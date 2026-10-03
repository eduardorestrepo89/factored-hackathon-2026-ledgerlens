"""Tests for the transaction_fraud_detection Lambda handler."""

import importlib
import json
import logging
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
)
from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (  # noqa: E501
    TransactionFraudDetectionUseCase,
)
from transaction_fraud_detection_lambda.delivery.dependencies.dependencies_builder import (  # noqa: E501
    build_database_repository,
    build_query_provider,
)
from transaction_fraud_detection_lambda.delivery.settings import (
    ClockSettings,
    DatabaseEngine,
)
from transaction_fraud_detection_lambda.domain.errors import (
    CardNotFoundError,
    DataSourceUnavailableError,
    FraudCheckDataIntegrityError,
    FraudCheckLookupError,
    TransactionNotFoundError,
)

from .fakes import (
    CUSTOMER_ID,
    SCORE,
    TRANSACTION_ID,
    FakeConnector,
    FakeFraudRepository,
    FakeQueryProvider,
    Outcome,
    fraud_responses,
    make_any_row,
    make_transaction_row,
)

pytestmark = pytest.mark.unit

TX_EVENT = {"customer_id": CUSTOMER_ID, "transaction_id": TRANSACTION_ID}
CARD_EVENT = {"customer_id": CUSTOMER_ID, "card_last4": "4497"}
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)
SUFFIX = " Ask the customer to confirm and retry."


def make_context(
    tool_name: str = "target___transaction_fraud_detection",
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
    import transaction_fraud_detection_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, Outcome] | None = None,
) -> FakeFraudRepository:
    """Point the handler at a use case over a fake repository and a fixed clock."""
    database_repository = FakeFraudRepository(
        fraud_responses() if responses is None else responses
    )
    use_case = TransactionFraudDetectionUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))
    return database_repository


def wire_connector(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any
) -> None:
    """Point the handler at real adapters over a fake connector and a fixed clock."""
    use_case = TransactionFraudDetectionUseCase(
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


def test_transaction_mode_returns_the_assessment(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    payload = body(module.handler(TX_EVENT, make_context()))

    assert payload["mode"] == "transaction"
    assert payload["assessment"]["transaction_id"] == TRANSACTION_ID
    assert payload["assessment"]["merchant_name"] == "Estación de Servicio"
    assert payload["assessment"]["verdict"] == "fraud"
    assert payload["assessment"]["basis"] == "scored"


def test_card_mode_returns_the_sweep(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    payload = body(module.handler(CARD_EVENT, make_context()))

    assert payload["mode"] == "card"
    assert payload["checked"] == 3
    assert payload["date_to"] == "2026-06-17T23:59:59"
    assert [item["verdict"] for item in payload["flagged"]] == ["fraud"]
    assert payload["truncated"] is False


def test_the_text_keeps_accents_unescaped(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    response = module.handler(TX_EVENT, make_context())

    assert "Estación" in response["content"][0]["text"]


def test_success_over_real_adapters(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(module, monkeypatch, FakeConnector([make_any_row()]))

    payload = body(module.handler(CARD_EVENT, make_context()))

    assert (payload["checked"], len(payload["flagged"])) == (3, 1)


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

    module.handler(TX_EVENT, make_context())
    module.handler(TX_EVENT, make_context())

    sent = [params["as_of"] for _name, params in database_repository.calls]
    assert sent == [AS_OF_SQL, datetime(2026, 6, 18, 8, 30)]


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (
            None,
            "Invalid value for 'customer_id': is required and must be a "
            "non-empty string." + SUFFIX,
        ),
        (
            {"customer_id": CUSTOMER_ID},
            "Invalid value for 'transaction_id': give either transaction_id "
            "(one charge) or card_last4 (sweep of that card's last 30 days)." + SUFFIX,
        ),
        (
            {**TX_EVENT, "card_last4": "4497"},
            "Invalid value for 'transaction_id': give either transaction_id or "
            "card_last4, not both." + SUFFIX,
        ),
        (
            {"customer_id": CUSTOMER_ID, "card_last4": "449"},
            "Invalid value for 'card_last4': must be exactly 4 digits." + SUFFIX,
        ),
    ],
)
def test_invalid_input_returns_its_message_without_a_query(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    event: object,
    message: str,
) -> None:
    database_repository = wire(module, monkeypatch)

    assert module.handler(event, make_context()) == {"error": message}
    assert database_repository.calls == []


@pytest.mark.parametrize(
    ("event", "responses", "message"),
    [
        (
            TX_EVENT,
            fraud_responses(fraud_transaction=[]),
            TransactionNotFoundError.MESSAGE,
        ),
        (
            CARD_EVENT,
            fraud_responses(fraud_card_exists=[]),
            CardNotFoundError.MESSAGE,
        ),
        (
            TX_EVENT,
            fraud_responses(fraud_transaction=DataSourceConnectionError("down")),
            DataSourceUnavailableError.MESSAGE,
        ),
        (
            CARD_EVENT,
            fraud_responses(fraud_card_sweep=QueryExecutionError("boom")),
            FraudCheckLookupError.MESSAGE,
        ),
        (
            TX_EVENT,
            fraud_responses(fraud_transaction=[make_transaction_row(fraud_score="x")]),
            FraudCheckDataIntegrityError.MESSAGE,
        ),
    ],
    ids=["tx-not-found", "card-not-found", "unavailable", "lookup", "integrity"],
)
def test_a_domain_error_returns_its_message(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    event: dict[str, Any],
    responses: dict[str, Outcome],
    message: str,
) -> None:
    wire(module, monkeypatch, responses)

    assert module.handler(event, make_context()) == {"error": message}


def test_query_failure_over_real_adapters_returns_the_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "transactions" does not exist')
    wire_connector(module, monkeypatch, FakeConnector(error))

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": FraudCheckLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("target___list_card_transactions"),
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

    response = module.handler(TX_EVENT, context)

    assert set(response) == {"error"}
    assert "transaction_fraud_detection" in response["error"]
    assert database_repository.calls == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    response = module.handler(TX_EVENT, make_context("transaction_fraud_detection"))

    assert "content" in response


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error running the fraud check. "
        "Offer a hand-off to a human agent."
    )
    assert "hunter2" not in response["error"]


def test_missing_configuration_returns_data_source_unavailable(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)
    monkeypatch.setattr(module, "CLOCK", None)

    response = module.handler(TX_EVENT, make_context())

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

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            TX_EVENT,
            "transaction_fraud_detection mode=transaction verdict_counts={'fraud': 1}",
        ),
        (
            CARD_EVENT,
            "transaction_fraud_detection mode=card verdict_counts={'fraud': 1}",
        ),
    ],
)
def test_success_log_names_the_verdicts_but_no_customer_data_or_score(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    event: dict[str, Any],
    expected: str,
) -> None:
    wire(module, monkeypatch)
    caplog.set_level(logging.INFO)

    module.handler(event, make_context())

    assert expected in caplog.text
    assert CUSTOMER_ID not in caplog.text
    assert str(SCORE) not in caplog.text
    assert "Estaci" not in caplog.text


def test_a_clean_sweep_logs_empty_counts(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire(module, monkeypatch, fraud_responses(fraud_card_sweep=[]))
    caplog.set_level(logging.INFO)

    module.handler(CARD_EVENT, make_context())

    assert "transaction_fraud_detection mode=card verdict_counts={}" in caplog.text
