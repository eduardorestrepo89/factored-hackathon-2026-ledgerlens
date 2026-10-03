"""Drift tests: the SQL files and tool_spec.json must match the Python contracts."""

import dataclasses
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from get_session_context_lambda.application.use_cases.get_session_context import (
    GetSessionContextUseCase,
)
from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    TransactionFlag,
)
from get_session_context_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeQueryProvider,
    FakeSessionRepository,
    session_responses,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/get_session_context"
QUERIES_DIR = TOOL_ROOT / "get_session_context_lambda/queries/postgresql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
SQL_COMMENT = re.compile(r"--[^\n]*")
AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
# The accent is built from its code point (NFC U+00E9), so this test file's own
# encoding can't change the expected values.
E_ACUTE = chr(0xE9)
CREDIT_CARD_FILTER = f"p.product_type = 'Tarjeta Cr{E_ACUTE}dito'"
CREDIT_CARD_PAGE = f"'Tarjeta de Cr{E_ACUTE}dito'"
# The entity each query's rows are mapped to.
QUERY_ENTITIES: dict[str, type] = {
    "session_customer_profile": Customer,
    "session_credit_cards": CreditCard,
    "session_recent_transactions": RecentTransaction,
    "session_digital_signals": DigitalSignal,
    "session_open_cases": OpenCase,
}
SENSITIVE_CUSTOMER_COLUMNS = (
    "document_number",
    "document_type",
    "date_of_birth",
    "gender",
    "email",
    "mobile_phone",
    "landline_phone",
    "credit_score",
    "estimated_monthly_income",
)
SIGNALS = (
    "FAILED_ACTION",
    "REVIEWING_TRANSACTIONS",
    "VIEWING_CREDIT_CARD",
    "SEEKING_HELP",
)


def sql(name: str) -> str:
    """Load one of the real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def flat_sql(name: str) -> str:
    """Return the query without comments, every run of whitespace one space."""
    return " ".join(SQL_COMMENT.sub("", sql(name)).split())


def sent_params() -> dict[str, dict[str, object]]:
    """Return the params the use case actually sends, keyed by query name."""
    database_repository = FakeSessionRepository(session_responses())
    GetSessionContextUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    ).execute(CUSTOMER_ID, as_of=AS_OF)
    return dict(database_repository.calls)


def test_the_query_list_matches_the_sql_folder() -> None:
    assert sorted(path.stem for path in QUERIES_DIR.glob("*.sql")) == sorted(
        QUERY_NAMES
    )
    assert list(QUERY_ENTITIES) == list(QUERY_NAMES)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == set(sent_params()[name])


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed,
    # including inside comments.
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_sets_no_session_parameters(name: str) -> None:
    # DSQL rejects most session parameters (statement_timeout among them).
    text = sql(name)

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


def test_session_statement_check_ignores_offset() -> None:
    assert SESSION_STATEMENT.search("SELECT 1\nOFFSET 0\n") is None
    assert SESSION_STATEMENT.search("SELECT 1;\n  set statement_timeout = 0;\n")


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_is_nfc_utf8_without_bom(name: str) -> None:
    # A decomposed accent or a BOM would silently match nothing (risk C1).
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_selects_every_column_the_use_case_maps(name: str) -> None:
    text = flat_sql(name)

    for field in dataclasses.fields(QUERY_ENTITIES[name]):
        if field.name == "flags":
            continue
        assert re.search(rf"\b{field.name}\b", text), field.name


def test_transactions_select_one_column_per_flag() -> None:
    text = flat_sql("session_recent_transactions")

    for flag in TransactionFlag:
        assert f"AS is_{flag.value}" in text, flag.value


def test_profile_selects_no_sensitive_column() -> None:
    text = flat_sql("session_customer_profile")

    assert "c.*" not in text
    for column in SENSITIVE_CUSTOMER_COLUMNS:
        assert column not in text, column


def test_profile_reads_one_customer_keeping_the_latest_copy() -> None:
    text = flat_sql("session_customer_profile")

    assert "SELECT DISTINCT ON (c.customer_id)" in text
    assert "WHERE c.customer_id = %(customer_id)s" in text
    assert "ORDER BY c.customer_id, c.last_updated DESC NULLS LAST" in text


@pytest.mark.parametrize(
    "name", ["session_credit_cards", "session_recent_transactions"]
)
def test_cards_and_transactions_are_credit_cards_only(name: str) -> None:
    text = flat_sql(name)

    assert CREDIT_CARD_FILTER in text
    assert "ILIKE" not in text.upper()


def test_credit_cards_lists_active_cards_first() -> None:
    assert (
        "ORDER BY (deduplicated.product_status = 'Active') DESC NULLS LAST, "
        "deduplicated.expiration_date DESC NULLS LAST, "
        "deduplicated.product_id LIMIT %(limit)s"
    ) in flat_sql("session_credit_cards")


def test_transactions_window_baseline_and_flags() -> None:
    text = flat_sql("session_recent_transactions")

    assert "t.process_date >= (%(as_of)s::date - 90)" in text
    assert "t.transaction_date <= %(as_of)s" in text
    assert "transaction_date >= %(as_of)s - INTERVAL '72 hours'" in text
    assert "transaction_date < %(as_of)s - INTERVAL '72 hours'" in text
    assert "percentile_cont(0.95) WITHIN GROUP (ORDER BY amount_usd)" in text
    assert "WHERE transaction_status = 'Approved'" in text
    assert "(r.transaction_status = 'Declined') AS is_declined" in text
    assert re.search(
        r"\(lower\(translate\(btrim\(r\.transaction_country\), '[^']+', '[^']+'\)\) "
        r"<> lower\(translate\(btrim\(h\.country\), '[^']+', '[^']+'\)\)\) "
        r"AS is_foreign",
        text,
    )
    assert (
        "(r.amount_usd > COALESCE(b.p95_usd, 'Infinity')) AS is_above_usual_amount"
    ) in text
    assert "r.merchant_name IS NOT NULL AND NOT EXISTS" in text
    assert "LEFT JOIN home AS h ON TRUE" in text
    assert (
        "ORDER BY r.transaction_date DESC NULLS LAST, r.transaction_id LIMIT %(limit)s"
    ) in text


def test_signals_map_the_confirmed_values_in_order() -> None:
    text = flat_sql("session_digital_signals")
    rules = [
        "WHEN e.event_type = 'Error' THEN 'FAILED_ACTION'",
        "WHEN e.page_title = 'Mis Movimientos' OR e.action = 'view_transactions' "
        "THEN 'REVIEWING_TRANSACTIONS'",
        f"WHEN e.page_title = {CREDIT_CARD_PAGE} THEN 'VIEWING_CREDIT_CARD'",
        "WHEN e.page_title = 'Ayuda' OR e.action = 'view_help' THEN 'SEEKING_HELP'",
    ]

    positions = [text.find(rule) for rule in rules]
    assert -1 not in positions, positions
    assert positions == sorted(positions)
    for signal in SIGNALS:
        assert f"'{signal}'" in text
    assert "ILIKE" not in text.upper()


def test_signals_window_and_filter() -> None:
    text = flat_sql("session_digital_signals")

    assert "e.process_date >= (%(as_of)s::date - 1)" in text
    assert "e.event_date > %(as_of)s - INTERVAL '24 hours'" in text
    assert "e.event_date <= %(as_of)s" in text
    assert "WHERE signals.signal IS NOT NULL" in text
    assert (
        "ORDER BY signals.event_date DESC NULLS LAST, signals.event_id LIMIT %(limit)s"
    ) in text


def test_open_cases_are_the_ones_open_at_as_of() -> None:
    text = flat_sql("session_open_cases")

    assert "k.creation_date <= %(as_of)s" in text
    assert "(k.closing_date IS NULL OR k.closing_date > %(as_of)s)" in text
    assert "NOT IN" not in text.upper()
    assert ("(%(as_of)s::date - deduplicated.creation_date::date) AS days_open") in text
    assert (
        "ORDER BY deduplicated.sla_breached DESC NULLS LAST, "
        "deduplicated.creation_date DESC NULLS LAST, "
        "deduplicated.complaint_id LIMIT %(limit)s"
    ) in text


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "get_session_context"
    assert spec["inputSchema"]["required"] == ["customer_id"]


def test_tool_spec_has_only_the_customer_id_property() -> None:
    properties = tool_spec()["inputSchema"]["properties"]

    assert set(properties) == {"customer_id"}
    assert properties["customer_id"]["type"] == "string"


def test_tool_spec_description_names_flags_signals_and_the_lists() -> None:
    description = tool_spec()["description"]

    for flag in TransactionFlag:
        assert flag.value in description, flag.value
    for signal in SIGNALS:
        assert signal in description, signal
    assert "'unavailable'" in description
    assert "'truncated'" in description
    assert "at most 25 items (5 open cases)" in description


def country_key(sql_text: str, column: str, value: str) -> str:
    """Apply the SQL's lower(translate(btrim(column), from, to)) to ``value``."""
    match = re.search(
        r"lower\(translate\(btrim\("
        + re.escape(column)
        + r"\), '([^']+)', '([^']+)'\)\)",
        sql_text,
    )
    assert match is not None, column
    source, target = match.groups()
    assert len(source) == len(target)
    return value.strip().translate(str.maketrans(source, target)).lower()


@pytest.mark.parametrize(
    ("transaction_country", "customer_country"),
    [
        ("México", "Mexico"),
        ("Mexico", "México"),
        ("PERÚ", "Perú"),
        ("Colombia ", "colombia"),
        ("Panamá", "Panama"),
    ],
)
def test_is_foreign_ignores_accents_case_and_spaces(
    transaction_country: str, customer_country: str
) -> None:
    # transaction_country holds names and mixes Mexico/México (ERD notes), so a
    # plain <> would flag domestic charges as foreign.
    text = flat_sql("session_recent_transactions")

    assert country_key(text, "r.transaction_country", transaction_country) == (
        country_key(text, "h.country", customer_country)
    )


def test_is_foreign_still_tells_different_countries_apart() -> None:
    text = flat_sql("session_recent_transactions")

    assert country_key(text, "r.transaction_country", "Chile") != country_key(
        text, "h.country", "Colombia"
    )
