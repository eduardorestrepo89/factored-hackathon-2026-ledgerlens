"""Tests for the Lambda settings read from environment variables."""

from datetime import datetime, timedelta, timezone

import pytest
from list_credit_cards_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
DSQL_ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}


def test_database_settings_default_to_aurora_dsql_and_25_rows() -> None:
    assert DatabaseSettings.from_env({}) == DatabaseSettings(
        engine=DatabaseEngine.AURORA_DSQL, max_rows=25
    )


@pytest.mark.parametrize("raw", ["aurora_dsql", " Aurora_DSQL ", "", "  "])
def test_db_engine_is_trimmed_lower_cased_and_defaulted(raw: str) -> None:
    settings = DatabaseSettings.from_env({"DB_ENGINE": raw})

    assert settings.engine is DatabaseEngine.AURORA_DSQL


@pytest.mark.parametrize("raw", ["postgresql", "oracle", "dsql"])
def test_unsupported_db_engine_is_rejected(raw: str) -> None:
    with pytest.raises(ConfigurationError, match="DB_ENGINE.*aurora_dsql"):
        DatabaseSettings.from_env({"DB_ENGINE": raw})


def test_max_rows_can_be_overridden() -> None:
    assert DatabaseSettings.from_env({"MAX_ROWS": " 10 "}).max_rows == 10


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "2.5"])
def test_invalid_max_rows_is_rejected(raw: str) -> None:
    with pytest.raises(ConfigurationError, match="MAX_ROWS"):
        DatabaseSettings.from_env({"MAX_ROWS": raw})


def test_dsql_settings_read_endpoint_and_region_and_default_the_user() -> None:
    assert DsqlSettings.from_env(DSQL_ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ll_read"
    )


def test_dsql_settings_trim_every_value_and_read_the_user() -> None:
    env = {
        "DSQL_CLUSTER_ENDPOINT": f"  {ENDPOINT}  ",
        "AWS_REGION": " us-east-1 ",
        "DSQL_DB_USER": " admin ",
    }

    assert DsqlSettings.from_env(env) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="admin"
    )


def test_a_blank_db_user_falls_back_to_the_read_only_role() -> None:
    settings = DsqlSettings.from_env({**DSQL_ENV, "DSQL_DB_USER": "   "})

    assert settings.db_user == "ll_read"


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "   ",
        f"https://{ENDPOINT}",
        f"{ENDPOINT}:5432",
        f"{ENDPOINT}/",
        "abc123",
    ],
)
def test_invalid_cluster_endpoint_is_rejected(endpoint: str) -> None:
    with pytest.raises(ConfigurationError, match="DSQL_CLUSTER_ENDPOINT"):
        DsqlSettings.from_env({**DSQL_ENV, "DSQL_CLUSTER_ENDPOINT": endpoint})


def test_missing_cluster_endpoint_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="DSQL_CLUSTER_ENDPOINT"):
        DsqlSettings.from_env({"AWS_REGION": "us-east-1"})


@pytest.mark.parametrize(
    "env", [{"DSQL_CLUSTER_ENDPOINT": ENDPOINT}, {**DSQL_ENV, "AWS_REGION": " "}]
)
def test_missing_region_is_rejected(env: dict[str, str]) -> None:
    with pytest.raises(ConfigurationError, match="AWS_REGION"):
        DsqlSettings.from_env(env)


def test_an_endpoint_in_another_region_than_aws_region_is_rejected() -> None:
    env = {**DSQL_ENV, "AWS_REGION": "us-west-2"}

    with pytest.raises(ConfigurationError, match="DSQL_CLUSTER_ENDPOINT.*AWS_REGION"):
        DsqlSettings.from_env(env)


def test_a_custom_endpoint_host_skips_the_region_check() -> None:
    # PrivateLink and other custom hosts don't carry the region in their name.
    env = {"DSQL_CLUSTER_ENDPOINT": "dsql.internal.example", "AWS_REGION": "us-west-2"}

    assert DsqlSettings.from_env(env).cluster_endpoint == "dsql.internal.example"


UTC = timezone.utc


def test_as_of_is_unset_by_default() -> None:
    assert ClockSettings.from_env({}) == ClockSettings(as_of=None)


@pytest.mark.parametrize("raw", ["", "   "])
def test_a_blank_as_of_uses_the_real_clock(raw: str) -> None:
    assert ClockSettings.from_env({"AS_OF": raw}).as_of is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-14", datetime(2026, 3, 14, tzinfo=UTC)),
        ("2026-03-14T10:30:00", datetime(2026, 3, 14, 10, 30, tzinfo=UTC)),
        ("2026-03-14T10:30:00-05:00", datetime(2026, 3, 14, 15, 30, tzinfo=UTC)),
        ("2026-03-14T10:30:00Z", datetime(2026, 3, 14, 10, 30, tzinfo=UTC)),
        (" 2026-03-14T10:30:00Z ", datetime(2026, 3, 14, 10, 30, tzinfo=UTC)),
    ],
)
def test_as_of_is_parsed_as_utc(raw: str, expected: datetime) -> None:
    as_of = ClockSettings.from_env({"AS_OF": raw}).as_of

    assert as_of == expected
    assert as_of is not None
    assert as_of.tzinfo == UTC


@pytest.mark.parametrize(
    "raw",
    [
        "yesterday",
        "2026-13-01",
        "14/03/2026",
        "now",
        # Valid ISO, but converting to UTC overflows datetime.min.
        "0001-01-01T00:00:00+01:00",
    ],
)
def test_invalid_as_of_is_rejected(raw: str) -> None:
    with pytest.raises(
        ConfigurationError, match="AS_OF must be an ISO 8601 date or timestamp"
    ):
        ClockSettings.from_env({"AS_OF": raw})


def test_now_returns_as_of_when_set() -> None:
    as_of = datetime(2026, 3, 14, 10, 30, tzinfo=UTC)

    assert ClockSettings(as_of=as_of).now() == as_of


def test_now_is_the_real_utc_time_when_unset() -> None:
    clock = ClockSettings(as_of=None)

    before = datetime.now(UTC)
    first = clock.now()
    second = clock.now()
    after = datetime.now(UTC)

    assert before <= first <= second <= after
    assert first.tzinfo == UTC
    assert after - before < timedelta(seconds=5)
