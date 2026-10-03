"""Drift tests: the SQL files must match the Python contracts and the schema."""

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pytest
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.infrastructure.queries.file_query_provider import (
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
TOOL_ROOT = REPO_ROOT / "gateway/tools/block_credit_card"
QUERIES_DIR = TOOL_ROOT / "block_credit_card_lambda/queries/postgresql"
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
    """Return the param names the use case sends, per query, on the blocking path."""
    repository = FakeDatabaseRepository(
        {"find_credit_card": [make_row()], "block_credit_card": [{"product_id": "P"}]}
    )
    BlockCreditCardUseCase(
        database_repository=repository, query_provider=FakeQueryProvider()
    ).execute(
        customer_id=CUSTOMER_ID,
        card_last4="4821",
        reason="lost",
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
    # psycopg treats every '%' as a placeholder marker, including inside comments.
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_each_file_is_one_statement_that_sets_no_session_parameter(name: str) -> None:
    found = statements(sql(name))

    assert len(found) == 1
    assert not found[0].upper().startswith("SET ")
    assert "statement_timeout" not in sql(name).lower()


def test_find_filters_on_the_exact_credit_card_literal_in_nfc_utf8() -> None:
    raw = (QUERIES_DIR / "find_credit_card.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert CREDIT_CARD_FILTER.encode("utf-8") in raw
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


def test_find_reads_only_the_customers_matching_cards_and_at_most_two() -> None:
    text = flat_sql("find_credit_card")

    assert (
        "FROM products AS p WHERE p.customer_id = %(customer_id)s "
        f"AND {CREDIT_CARD_FILTER} "
        "AND RIGHT(p.product_number, 4) = %(card_last4)s"
    ) in text
    assert text.endswith("ORDER BY p.product_id LIMIT 2")


def test_block_only_changes_a_card_that_is_neither_blocked_nor_closed() -> None:
    assert (
        "UPDATE products SET product_status = 'Blocked', "
        "last_updated = %(last_updated)s "
        "WHERE product_id = %(product_id)s AND customer_id = %(customer_id)s "
        "AND product_status NOT IN ('Blocked', 'Closed') RETURNING product_id"
    ) in flat_sql("block_credit_card")


def test_the_statuses_used_pass_the_products_check_constraint() -> None:
    products = load_plan().data_tables["products"]

    for status in ("'Blocked'", "'Closed'", "'Active'", "'Suspended'"):
        assert status in products


def tool_spec() -> dict:
    """Load the single tool definition from tool_spec.json."""
    import json

    specs = json.loads((TOOL_ROOT / "tool_spec.json").read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_name_inputs_and_required_fields() -> None:
    from block_credit_card_lambda.application.use_cases.block_credit_card import (
        REASONS,
    )

    spec = tool_spec()
    properties = spec["inputSchema"]["properties"]

    assert spec["name"] == "block_credit_card"
    assert spec["inputSchema"]["required"] == [
        "customer_id",
        "card_last4",
        "reason",
        "customer_confirmed",
    ]
    assert set(properties) == {
        "customer_id",
        "card_last4",
        "reason",
        "customer_confirmed",
    }
    assert set(properties["reason"]["enum"]) == set(REASONS)
    assert properties["customer_confirmed"]["type"] == "boolean"


def test_tool_spec_description_demands_an_explicit_yes() -> None:
    description = tool_spec()["description"]

    assert "Only call after the customer explicitly said yes" in description
    assert "'already_blocked'" in description
