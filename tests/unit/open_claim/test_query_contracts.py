"""Drift tests: the SQL files must match the Python contracts and the schema."""

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pytest
from open_claim_lambda.application.use_cases.open_claim import (
    SUBCATEGORIES,
    OpenClaimUseCase,
)
from open_claim_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from data_load.ddl import load_plan

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeDatabaseRepository,
    FakeQueryProvider,
    make_row,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/open_claim"
QUERIES_DIR = TOOL_ROOT / "open_claim_lambda/queries/postgresql"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Cr\u00e9dito'"


def sql(name: str) -> str:
    """Load one of the tool's real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def flat_sql(name: str) -> str:
    """Return the query with every run of whitespace collapsed to one space."""
    return " ".join(sql(name).split())


def statements(text: str) -> list[str]:
    """Split SQL text into statements, ignoring -- comments."""
    without_comments = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def sent_params() -> dict[str, set[str]]:
    """Return the param names the use case sends, per query, on the full path."""
    repository = FakeDatabaseRepository(
        {
            "claim_transactions": [make_row()],
            "insert_claim": [{"complaint_id": "CMP-X"}],
            "resolution_estimate": [{"median_days": 5, "p90_days": 9}],
        }
    )
    OpenClaimUseCase(
        database_repository=repository, query_provider=FakeQueryProvider()
    ).execute(
        customer_id=CUSTOMER_ID,
        transaction_ids=["TRX-1"],
        claim_type="fraud",
        customer_statement="No lo reconozco",
        customer_confirmed=True,
        now=datetime(2026, 6, 17, tzinfo=timezone.utc),
    )
    return {name: set(params) for name, params in repository.calls}


def test_the_use_case_runs_exactly_the_tools_queries() -> None:
    assert set(sent_params()) == set(QUERY_NAMES)
    assert {path.stem for path in QUERIES_DIR.glob("*.sql")} == set(QUERY_NAMES)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == sent_params()[name]


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_each_file_is_one_statement_that_sets_no_session_parameter(name: str) -> None:
    found = statements(sql(name))

    assert len(found) == 1
    assert not found[0].upper().startswith("SET ")
    assert "statement_timeout" not in sql(name).lower()


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_files_are_nfc_utf8_without_bom(name: str) -> None:
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


def test_transactions_are_the_customers_and_on_a_credit_card() -> None:
    text = flat_sql("claim_transactions")

    assert "WHERE t.customer_id = %(customer_id)s" in text
    assert "AND t.transaction_id = ANY(%(transaction_ids)s)" in text
    assert f"AND {CREDIT_CARD_FILTER}" in text


def test_the_insert_writes_a_claim_with_values_the_schema_accepts() -> None:
    text = flat_sql("insert_claim")
    complaints = load_plan().data_tables["complaints"]

    assert "'Claim', 'Transactions'" in text
    assert "'Web'" in text
    assert "'Open', false, false" in text
    assert "RETURNING complaint_id" in text
    # category and reception_channel have CHECK constraints in schema.sql.
    assert "'Transactions'" in complaints
    assert "'Web'" in complaints
    assert "'Cards'" not in text
    assert "AI Assistant" not in text


def test_the_subcategories_are_the_datasets_values() -> None:
    assert SUBCATEGORIES == {
        "fraud": "Cargo no reconocido",
        "dispute": "Cobro indebido",
    }


def test_the_estimate_uses_similar_claims_from_enough_history() -> None:
    text = flat_sql("resolution_estimate")

    assert "percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_days)" in text
    assert "percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_days)" in text
    assert (
        "WHERE case_type = 'Claim' AND category = 'Transactions' "
        "AND subcategory = %(subcategory)s AND resolution_days IS NOT NULL "
        "AND creation_date >= %(since)s HAVING COUNT(*) >= 20"
    ) in text
    # The header comment names the column on purpose; the statement never reads it.
    assert "compensation_granted" not in statements(sql("resolution_estimate"))[0]
