"""schema.sql is the single contract for DuckDB (validation) and Aurora DSQL."""

import re

import duckdb
import pytest

from data_load.ddl import load_plan

BANK_PII = {
    "pii.customers",
    "pii.service_agents",
    "bank.products",
    "bank.branches",
    "bank.marketing_campaigns",
    "bank.daily_exchange_rates",
    "bank.transactions",
    "bank.call_center_interactions",
    "bank.call_transcripts",
    "bank.satisfaction_surveys",
    "bank.digital_events",
    "bank.complaints",
    "bank.campaign_sends",
}


@pytest.mark.unit
def test_plan_groups_every_statement():
    plan = load_plan()
    assert set(plan.data_tables) == BANK_PII
    assert set(plan.views) == {"bank.customer_profile", "bank.agent_roster"}
    assert len(plan.app_tables) == 7
    assert set(plan.roles) == {"ll_read", "ll_write", "ll_approvals", "ll_feedback"}
    assert len(plan.data_indexes) == 3
    assert set(plan.app_indexes) == {
        "idx_cases_customer_date",
        "idx_claims_customer_date",
    }


@pytest.mark.unit
def test_unknown_statement_is_rejected():
    with pytest.raises(ValueError, match="unclassified"):
        load_plan("DROP TABLE bank.transactions;")


@pytest.mark.unit
def test_duckdb_builds_every_data_table():
    plan = load_plan()
    con = duckdb.connect()
    for stmt in plan.schemas + list(plan.data_tables.values()):
        con.execute(stmt)
    count = con.sql(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema IN ('bank', 'pii')"
    ).fetchone()[0]
    assert count == 13


@pytest.mark.unit
def test_schema_fixes_from_the_spec():
    plan = load_plan()
    transcripts = plan.data_tables["bank.call_transcripts"]
    assert "duration_seconds integer NOT NULL" not in transcripts
    assert "AI Assistant" not in plan.data_tables["bank.complaints"]
    cases = next(s for s in plan.app_tables if "app.cases" in s)
    assert "claim_id varchar(40)" in cases and "complaint_id" not in cases


@pytest.mark.unit
def test_app_roles_cannot_write_or_see_organizer_data():
    for grant in load_plan().grants:
        m = re.fullmatch(r"GRANT (.+) ON (.+) TO \w+", grant)
        assert m, grant
        privileges = m[1]
        objects = [o.strip() for o in m[2].replace("SCHEMA ", "").split(",")]
        assert not any(o.startswith("pii") for o in objects), grant
        if privileges not in ("SELECT", "USAGE"):
            assert not any(o.startswith("bank") for o in objects), grant
