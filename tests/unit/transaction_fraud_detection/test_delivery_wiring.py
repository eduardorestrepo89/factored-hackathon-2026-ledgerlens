"""Tests for the dependency wiring of the transaction_fraud_detection tool."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import transaction_fraud_detection_lambda.utils.connectors.dsql as dsql_module
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (  # noqa: E501
    TransactionFraudDetectionUseCase,
)
from transaction_fraud_detection_lambda.delivery.dependencies import (
    dependencies_builder,
)
from transaction_fraud_detection_lambda.delivery.dependencies.dependencies_builder import (  # noqa: E501
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_query_provider,
    build_settings,
    build_transaction_fraud_detection_use_case,
)
from transaction_fraud_detection_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    FraudVerdict,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)
from transaction_fraud_detection_lambda.infrastructure.repositories.dsql_repository import (  # noqa: E501
    DsqlRepository,
)
from transaction_fraud_detection_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeConnector,
    make_any_row,
)

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
SETTINGS = DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL, max_rows=25)
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)
TX_REQUEST = FraudCheckRequest(
    CUSTOMER_ID, transaction_id=TRANSACTION_ID, card_last4=None
)
CARD_REQUEST = FraudCheckRequest(CUSTOMER_ID, transaction_id=None, card_last4="4497")


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_dsql_settings_reads_the_environment() -> None:
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ll_read"
    )


def test_build_clock_reads_as_of() -> None:
    assert build_clock({"AS_OF": "2026-06-17T23:59:59"}) == ClockSettings(as_of=AS_OF)


def test_build_clock_without_as_of_uses_the_real_clock() -> None:
    assert build_clock({}) == ClockSettings(as_of=None)


def test_build_clock_with_a_bad_as_of_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for transaction_fraud_detection" in caplog.text


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
    assert "DISTINCT ON" in provider.get("fraud_transaction")


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "transaction_fraud_detection_lambda"


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


def executed(connector: FakeConnector) -> list[tuple[str, dict[str, object]]]:
    """Return (sql, params) of every query, in order, on the last connection."""
    return [
        (sql, dict(params))
        for cursor in connector.connections[-1].cursors
        for sql, params in cursor.executed
    ]


def test_one_charge_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_transaction_fraud_detection_use_case(ENV)
    assert isinstance(use_case, TransactionFraudDetectionUseCase)
    result = use_case.execute(TX_REQUEST, as_of=AS_OF)

    assert isinstance(result, FraudAssessment)
    assert result.verdict is FraudVerdict.FRAUD
    queries = executed(connector)
    assert len(queries) == 1
    assert "FROM transactions AS t" in queries[0][0]
    assert queries[0][1] == {
        "customer_id": CUSTOMER_ID,
        "transaction_id": TRANSACTION_ID,
        "as_of": AS_OF_SQL,
    }


def test_card_sweep_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_transaction_fraud_detection_use_case(ENV)
    assert use_case is not None
    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (result.checked, len(result.flagged)) == (3, 1)
    queries = executed(connector)
    assert len(queries) == 2
    assert "SELECT 1 AS card_exists" in queries[0][0]
    assert "WITH window_tx AS" in queries[1][0]
    assert queries[1][1] == {
        "customer_id": CUSTOMER_ID,
        "card_last4": "4497",
        "as_of": AS_OF_SQL,
        "review_above": Decimal("30"),
        "limit": 26,
    }


def test_use_case_uses_max_rows_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row() for _ in range(4)])
    use_fake_connector(monkeypatch, connector)

    use_case = build_transaction_fraud_detection_use_case({**ENV, "MAX_ROWS": "3"})
    assert use_case is not None
    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (len(result.flagged), result.truncated) == (3, True)
    assert executed(connector)[1][1]["limit"] == 4


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_transaction_fraud_detection_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        DataSourceConnectionError("no route to host"), [make_any_row()]
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_transaction_fraud_detection_use_case(ENV)

    assert use_case is not None
    assert isinstance(use_case.execute(CARD_REQUEST, as_of=AS_OF), CardSweep)


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
    assert build_transaction_fraud_detection_use_case(env) is None
