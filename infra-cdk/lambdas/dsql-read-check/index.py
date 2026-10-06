"""Stage 4 of the data pipeline: prove the tools' access path (spec sections 4.1 and 7).

Runs in the VPC with the tools role and logs in as ll_read through the private
endpoint. Every table must return a row; an INSERT must be refused.
"""

import os

import aurora_dsql_psycopg as dsql
import psycopg

TABLES = (
    "branches",
    "call_center_interactions",
    "call_transcripts",
    "campaign_sends",
    "complaints",
    "customers",
    "daily_exchange_rates",
    "digital_events",
    "marketing_campaigns",
    "products",
    "satisfaction_surveys",
    "service_agents",
    "transactions",
)


def check(conn) -> dict:
    with conn.cursor() as cur:
        for table in TABLES:
            cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
            if not cur.fetchall():
                raise RuntimeError(f"{table} is empty")
    try:
        with conn.transaction(), conn.cursor() as cur:
            # inserts nothing, but needs INSERT privilege; rolled back either way
            cur.execute("INSERT INTO branches SELECT * FROM branches WHERE false")
            raise RuntimeError(
                "ll_read could INSERT into branches: access is misconfigured"
            )
    except psycopg.errors.InsufficientPrivilege:
        return {"tables_read": len(TABLES), "insert_denied": True}


def handler(event, context):
    conn = dsql.connect(host=os.environ["DSQL_HOST"], user="ll_read", autocommit=True)
    try:
        return check(conn)
    finally:
        conn.close()
