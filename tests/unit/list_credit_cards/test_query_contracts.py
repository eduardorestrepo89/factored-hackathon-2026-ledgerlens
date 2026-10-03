"""Drift tests: the SQL file and tool_spec.json must match the Python contracts."""

import dataclasses
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from list_credit_cards_lambda.application.use_cases.list_credit_cards import (
    ListCreditCardsUseCase,
)
from list_credit_cards_lambda.domain.entities.credit_card import CreditCard
from list_credit_cards_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import CUSTOMER_ID, FakeDatabaseRepository, FakeQueryProvider

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/list_credit_cards"
QUERIES_DIR = TOOL_ROOT / "list_credit_cards_lambda/queries/postgresql"
SQL_FILE = QUERIES_DIR / "list_credit_cards.sql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Cr\u00e9dito'"


def sql() -> str:
    """Load the real list_credit_cards query."""
    return FileQueryProvider(QUERIES_DIR).get("list_credit_cards")


def flat_sql() -> str:
    """Return the query with every run of whitespace collapsed to one space."""
    return " ".join(sql().split())


def sent_params() -> dict[str, object]:
    """Return the params the use case actually sends to the database repository."""
    database_repository = FakeDatabaseRepository()
    ListCreditCardsUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    ).execute(CUSTOMER_ID)
    return database_repository.calls[0][1]


def test_sql_placeholders_match_the_use_case_params_exactly() -> None:
    assert set(PLACEHOLDER.findall(sql())) == set(sent_params())


def test_sql_has_no_stray_percent_signs() -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed,
    # including inside comments.
    assert "%" not in PLACEHOLDER.sub("", sql())


def test_sql_sets_no_session_parameters() -> None:
    # DSQL rejects most session parameters (statement_timeout among them). The
    # regex is anchored at line start so "OFFSET" or "SET" in a comment don't count.
    text = sql()

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


def test_session_statement_check_ignores_offset() -> None:
    assert SESSION_STATEMENT.search("SELECT 1\nOFFSET 0\n") is None
    assert SESSION_STATEMENT.search("SELECT 1;\n  set statement_timeout = 0;\n")


def test_sql_filters_on_the_exact_credit_card_product_type() -> None:
    text = sql()

    assert CREDIT_CARD_FILTER in text
    assert "ILIKE" not in text.upper()


def test_credit_card_literal_is_nfc_utf8_without_bom() -> None:
    # A decomposed accent or a BOM would silently match no cards (risk C1).
    raw = SQL_FILE.read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert CREDIT_CARD_FILTER.encode("utf-8") in raw
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


def test_sql_reads_only_the_customers_products() -> None:
    text = flat_sql()

    assert "FROM products AS p WHERE p.customer_id = %(customer_id)s" in text
    assert "JOIN" not in text.upper()


def test_sql_deduplicates_cards_keeping_the_latest_copy() -> None:
    text = flat_sql()

    assert "SELECT DISTINCT ON (p.product_id)" in text
    assert "ORDER BY p.product_id, p.last_updated DESC NULLS LAST" in text


def test_sql_lists_active_cards_first_then_latest_expiry() -> None:
    assert (
        "ORDER BY (deduplicated.product_status = 'Active') DESC NULLS LAST, "
        "deduplicated.expiration_date DESC NULLS LAST, "
        "deduplicated.product_id LIMIT %(limit)s"
    ) in flat_sql()


def test_sql_selects_every_column_the_use_case_maps() -> None:
    text = sql()

    for field in dataclasses.fields(CreditCard):
        assert re.search(rf"\b{field.name}\b", text), field.name
    assert "AS card_last4" in text
    assert "AS available_credit" in text


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "list_credit_cards"
    assert spec["inputSchema"]["required"] == ["customer_id"]


def test_tool_spec_has_only_the_customer_id_property() -> None:
    properties = tool_spec()["inputSchema"]["properties"]

    assert set(properties) == {"customer_id"}
    assert properties["customer_id"]["type"] == "string"


def test_tool_spec_description_states_the_cap_and_the_null_result() -> None:
    description = tool_spec()["description"]

    assert "at most 25 cards" in description
    assert "'cards' is null when the customer has no credit cards" in description
