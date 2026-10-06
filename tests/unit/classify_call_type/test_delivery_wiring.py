"""Tests for the dependency wiring of the classify_call_type tool."""

from decimal import Decimal

import classify_call_type_lambda.utils.connectors.dsql as dsql_module
import pytest
from classify_call_type_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from classify_call_type_lambda.application.use_cases.classify_call_type import (
    ClassifyCallTypeUseCase,
)
from classify_call_type_lambda.delivery.dependencies import dependencies_builder
from classify_call_type_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_classify_call_type_use_case,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_query_provider,
    build_settings,
)
from classify_call_type_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason
from classify_call_type_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from classify_call_type_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import (
    AS_OF,
    AS_OF_SQL,
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
# make_any_row, ranked: the flagged charge, P08's open case and the app error.
ANY_ROW_RANKING = [
    (CallReason.FRAUD_SUSPECTED, Decimal("0.77"), TRANSACTION_ID),
    (CallReason.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-FHCLR8TGWMBD0YFOCLYS"),
    (CallReason.FAILED_APP_ACTION, Decimal("0.58"), "EVT-0001"),
]


def ranking(result: CallClassification) -> list[tuple[CallReason, Decimal, str]]:
    """Return (reason, confidence, ref_id) of every ranked reason."""
    return [(item.reason, item.confidence, item.ref_id) for item in result.reasons]


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
    assert "Invalid AS_OF for classify_call_type" in caplog.text


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
    assert "DISTINCT ON" in provider.get("call_reason_transactions")


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "classify_call_type_lambda"


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


def test_use_case_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_classify_call_type_use_case(ENV)
    assert isinstance(use_case, ClassifyCallTypeUseCase)
    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert ranking(result) == ANY_ROW_RANKING
    assert result.unavailable == ()
    # The eager cold-start connection is the one every query runs on.
    assert len(connector.connections) == 1
    queries = executed(connector)
    assert len(queries) == 4
    assert "FROM transactions AS t" in queries[0][0]
    assert "FROM products AS p" in queries[1][0]
    assert "FROM complaints AS k" in queries[2][0]
    assert "FROM digital_events AS e" in queries[3][0]
    assert [params for _sql, params in queries] == [
        {
            "customer_id": CUSTOMER_ID,
            "as_of": AS_OF_SQL,
            "review_above": Decimal("30"),
            "limit": 201,
        },
        {"customer_id": CUSTOMER_ID},
        {"customer_id": CUSTOMER_ID, "as_of": AS_OF_SQL},
        {"customer_id": CUSTOMER_ID, "as_of": AS_OF_SQL},
    ]


def test_max_rows_is_still_parsed_but_unused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_classify_call_type_use_case({**ENV, "MAX_ROWS": "1"})

    assert use_case is not None
    assert ranking(use_case.execute(CUSTOMER_ID, AS_OF)) == ANY_ROW_RANKING


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_classify_call_type_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        DataSourceConnectionError("no route to host"), [make_any_row()]
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_classify_call_type_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(CUSTOMER_ID, AS_OF).unavailable == ()


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**ENV, "DB_ENGINE": "oracle"},
        {**ENV, "DB_ENGINE": "postgresql"},
        {**ENV, "MAX_ROWS": "0"},
        {"AWS_REGION": "us-east-1"},
        {"DSQL_CLUSTER_ENDPOINT": ENDPOINT},
        {**ENV, "DSQL_CLUSTER_ENDPOINT": f"https://{ENDPOINT}"},
    ],
)
def test_use_case_build_with_bad_configuration_returns_none(
    env: dict[str, str],
) -> None:
    assert build_classify_call_type_use_case(env) is None
