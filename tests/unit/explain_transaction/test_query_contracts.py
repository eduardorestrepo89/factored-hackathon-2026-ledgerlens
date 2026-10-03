"""Drift tests: the SQL files and tool_spec.json must match the Python contracts."""

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from explain_transaction_lambda.application.use_cases.explain_transaction import (
    ExplainTransactionUseCase,
)
from explain_transaction_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeExplainRepository,
    FakeQueryProvider,
    explain_responses,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/explain_transaction"
QUERIES_DIR = TOOL_ROOT / "explain_transaction_lambda/queries/postgresql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
TRANSLATE = re.compile(r"translate\(([^,]+), '([^']*)', '([^']*)'\)")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Crédito'"
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)

# The columns each query must select: the ones the use case maps (Task 4).
SELECTED_COLUMNS = {
    "explain_transaction": (
        "transaction_id",
        "transaction_date",
        "product_id",
        "card_last4",
        "card_currency",
        "card_expiration_date",
        "merchant_name",
        "merchant_category",
        "amount",
        "currency",
        "channel",
        "transaction_city",
        "transaction_country",
        "transaction_status",
        "response_code",
        "fx_sell_rate",
    ),
    "transaction_habit": (
        "history_count",
        "times_at_merchant",
        "same_currency_count",
        "usual_low",
        "usual_high",
        "country_seen_before",
    ),
    "transaction_app_activity": ("event_id", "event_date", "ip_country", "ip_city"),
}


def sql(name: str) -> str:
    """Load one of the real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def sent_params() -> dict[str, dict[str, object]]:
    """Return the params the use case actually sends, keyed by query name."""
    database_repository = FakeExplainRepository(explain_responses())
    use_case = ExplainTransactionUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)
    return dict(database_repository.calls)


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def strip_accents(text: str) -> str:
    """Drop combining marks: 'Ó' -> 'O', 'ñ' -> 'n'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def country_folds() -> list[tuple[str, str, str]]:
    """Return (argument, from_chars, to_chars) of each translate() in the habit SQL."""
    return [
        (arg.strip(), src, dst)
        for arg, src, dst in TRANSLATE.findall(sql("transaction_habit"))
    ]


# --- every query -----------------------------------------------------------------


def test_every_query_is_sent() -> None:
    assert set(sent_params()) == set(QUERY_NAMES)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == set(sent_params()[name])


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed.
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_sets_no_session_parameters(name: str) -> None:
    # DSQL rejects most session parameters (statement_timeout among them).
    text = sql(name)

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_no_query_reads_the_fraud_columns(name: str) -> None:
    # This tool explains; judging fraud is transaction_fraud_detection's job.
    # Comments count too.
    text = sql(name).lower()

    assert "fraud_score" not in text
    assert "is_fraud" not in text


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_each_query_checks_the_customer(name: str) -> None:
    assert "customer_id = %(customer_id)s" in sql(name)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_is_nfc_utf8_without_bom(name: str) -> None:
    # A decomposed accent or a BOM would silently match nothing.
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_selects_every_column_the_use_case_maps(name: str) -> None:
    text = sql(name)
    for column in SELECTED_COLUMNS[name]:
        assert column in text, column


# --- the core query ----------------------------------------------------------------


def test_core_is_credit_cards_only() -> None:
    raw = (QUERIES_DIR / "explain_transaction.sql").read_bytes()

    assert CREDIT_CARD_FILTER.encode("utf-8") in raw


def test_core_finds_one_charge_of_the_customer_up_to_as_of() -> None:
    text = sql("explain_transaction")

    assert "SELECT DISTINCT ON (t.transaction_id)" in text
    assert "t.transaction_id = %(transaction_id)s" in text
    assert "t.customer_id = %(customer_id)s" in text
    assert "t.transaction_date <= %(as_of)s" in text


def test_core_joins_the_rate_only_across_currencies() -> None:
    text = sql("explain_transaction")

    assert "LEFT JOIN daily_exchange_rates AS fx" in text
    assert "fx.date = t.transaction_date::date" in text
    assert "fx.source_currency = t.currency" in text
    assert "fx.target_currency = p.currency" in text
    assert "t.currency <> p.currency" in text
    assert "fx.sell_rate" in text


# --- the habit query ---------------------------------------------------------------


def test_habit_window_is_the_cards_approved_90_days_before_the_charge() -> None:
    text = sql("transaction_habit")

    assert "SELECT DISTINCT ON (t.transaction_id)" in text
    assert "t.product_id = %(product_id)s" in text
    assert "t.transaction_status = 'Approved'" in text
    assert "t.transaction_id <> %(transaction_id)s" in text
    assert "t.transaction_date >= %(charge_date)s - INTERVAL '90 days'" in text
    assert "t.transaction_date <  %(charge_date)s" in text


def test_habit_range_is_the_10th_to_90th_percentile_in_the_charge_currency() -> None:
    text = sql("transaction_habit")

    assert "percentile_cont(0.1) WITHIN GROUP (ORDER BY amount)" in text
    assert "percentile_cont(0.9) WITHIN GROUP (ORDER BY amount)" in text
    assert text.count("FILTER (WHERE currency = %(currency)s::text)") == 3


def test_habit_folds_the_country_on_both_sides_identically() -> None:
    folds = country_folds()

    assert [arg for arg, _, _ in folds] == [
        "btrim(transaction_country)",
        "btrim(%(transaction_country)s::text)",
    ]
    assert folds[0][1:] == folds[1][1:]


def test_habit_accent_mapping_strips_each_accent() -> None:
    _, src, dst = country_folds()[0]

    assert len(src) == len(dst)
    for accented, plain in zip(src, dst, strict=True):
        assert strip_accents(accented) == plain


def test_habit_accent_mapping_matches_list_card_transactions() -> None:
    # The same strings fold merchants there; one mapping keeps both tools alike.
    other = next(
        (REPO_ROOT / "gateway/tools/list_card_transactions").rglob(
            "list_card_transactions.sql"
        )
    )
    other_folds = TRANSLATE.findall(other.read_text(encoding="utf-8"))

    assert country_folds()[0][1:] == other_folds[0][1:]


# --- the app activity query ---------------------------------------------------------


def test_app_activity_is_the_closest_event_within_two_hours() -> None:
    text = sql("transaction_app_activity")

    assert "e.ip_country IS NOT NULL" in text
    assert (
        "e.event_date BETWEEN %(charge_date)s - INTERVAL '2 hours' "
        "AND %(charge_date)s + INTERVAL '2 hours'"
    ) in text
    assert "e.event_date <= %(as_of)s" in text
    assert "ORDER BY ABS(EXTRACT(EPOCH FROM (e.event_date - %(charge_date)s)))" in text
    assert text.rstrip().endswith("LIMIT 1")


# --- tool_spec.json ---------------------------------------------------------------


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "explain_transaction"
    assert spec["inputSchema"]["required"] == ["customer_id", "transaction_id"]


def test_tool_spec_properties_are_the_two_ids() -> None:
    properties = tool_spec()["inputSchema"]["properties"]

    assert set(properties) == {"customer_id", "transaction_id"}
    assert all(prop["type"] == "string" for prop in properties.values())


def test_tool_spec_description_names_the_sections() -> None:
    description = tool_spec()["description"]

    for word in (
        "fx",
        "decline",
        "habit",
        "app_activity",
        "unavailable",
        "transaction_fraud_detection",
        "2 decimals",
    ):
        assert word in description, word
