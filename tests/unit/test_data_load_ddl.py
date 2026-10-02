"""schema.sql is the single contract for DuckDB (validation) and Aurora DSQL."""

import re

import duckdb
import pytest

from data_load.ddl import load_plan, varchar_limits

TABLES = {
    "customers",
    "service_agents",
    "products",
    "branches",
    "marketing_campaigns",
    "daily_exchange_rates",
    "transactions",
    "call_center_interactions",
    "call_transcripts",
    "satisfaction_surveys",
    "digital_events",
    "complaints",
    "campaign_sends",
}


@pytest.mark.unit
def test_plan_groups_every_statement():
    plan = load_plan()
    assert set(plan.data_tables) == TABLES
    assert plan.roles == {"ll_read": "CREATE ROLE ll_read WITH LOGIN"}
    assert plan.grants == [
        "GRANT USAGE ON SCHEMA public TO ll_read",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO ll_read",
    ]
    assert [re.search(r"ON (\w+)", s)[1] for s in plan.indexes] == [
        "transactions",
        "products",
        "complaints",
    ]


@pytest.mark.unit
def test_unknown_statement_is_rejected():
    with pytest.raises(ValueError, match="unclassified"):
        load_plan("DROP TABLE transactions;")


@pytest.mark.unit
def test_duckdb_builds_every_data_table():
    con = duckdb.connect()
    for stmt in load_plan().data_tables.values():
        con.execute(stmt)
    assert {r[0] for r in con.sql("SHOW TABLES").fetchall()} == TABLES


@pytest.mark.unit
def test_tables_as_delivered_without_foreign_keys():
    plan = load_plan()
    assert not any("." in name for name in plan.data_tables)  # one schema: public
    assert not any("REFERENCES" in ddl for ddl in plan.data_tables.values())
    assert (
        "duration_seconds integer NOT NULL" not in plan.data_tables["call_transcripts"]
    )
    assert "AI Assistant" not in plan.data_tables["complaints"]


@pytest.mark.unit
def test_read_role_can_only_read():
    for grant in load_plan().grants:
        privileges = re.fullmatch(r"GRANT (.+) ON .+ TO ll_read", grant)[1]
        assert privileges in ("USAGE", "SELECT"), grant


@pytest.mark.unit
def test_varchar_limits_come_from_the_ddl():
    limits = varchar_limits(load_plan().data_tables["branches"])
    assert limits["branch_code"] == 10 and limits["branch_id"] == 30
    assert "latitude" not in limits  # numeric, not varchar
