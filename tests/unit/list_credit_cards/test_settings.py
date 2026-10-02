"""Tests for the Lambda settings read from environment variables."""

import pytest
from list_credit_cards_lambda.delivery.settings import (
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
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ledgerlens_readonly"
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

    assert settings.db_user == "ledgerlens_readonly"


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
