"""Drift tests: the SQL files and tool_spec.json must match the Python contracts."""

import dataclasses
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (  # noqa: E501
    TransactionFraudDetectionUseCase,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)
from transaction_fraud_detection_lambda.infrastructure.queries.file_query_provider import (  # noqa: E501
    FileQueryProvider,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeFraudRepository,
    FakeQueryProvider,
    fraud_responses,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/transaction_fraud_detection"
QUERIES_DIR = TOOL_ROOT / "transaction_fraud_detection_lambda/queries/postgresql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Crédito'"
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
MAPPED_COLUMNS = (
    "transaction_id",
    "transaction_date",
    "card_last4",
    "merchant_name",
    "amount",
    "currency",
    "transaction_status",
    "fraud_score",
)


def sql(name: str) -> str:
    """Load one of the real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def sent_params() -> dict[str, dict[str, object]]:
    """Return the params the use case actually sends, keyed by query name."""
    database_repository = FakeFraudRepository(fraud_responses())
    use_case = TransactionFraudDetectionUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    use_case.execute(
        FraudCheckRequest(CUSTOMER_ID, transaction_id=TRANSACTION_ID, card_last4=None),
        AS_OF,
    )
    use_case.execute(
        FraudCheckRequest(CUSTOMER_ID, transaction_id=None, card_last4="4497"), AS_OF
    )
    return dict(database_repository.calls)


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


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
def test_no_query_reads_the_outcome_label(name: str) -> None:
    # DEC-10: the label is only known after an investigation; the verdict
    # comes from the stored score alone. Comments count too.
    assert "is_fraud" not in sql(name).lower()


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_each_query_checks_the_customer_and_credit_cards(name: str) -> None:
    # Another customer's charge or card, or a debit card, must find nothing.
    text = sql(name)

    assert "customer_id = %(customer_id)s" in text
    assert CREDIT_CARD_FILTER in text


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_credit_card_literal_is_nfc_utf8_without_bom(name: str) -> None:
    # A decomposed accent or a BOM would silently match no transactions.
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert CREDIT_CARD_FILTER.encode("utf-8") in raw
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


@pytest.mark.parametrize("name", ["fraud_transaction", "fraud_card_sweep"])
def test_sql_selects_every_column_the_use_case_maps(name: str) -> None:
    text = sql(name)
    for column in MAPPED_COLUMNS:
        assert column in text, column


@pytest.mark.parametrize("name", ["fraud_transaction", "fraud_card_sweep"])
def test_sql_removes_duplicate_rows(name: str) -> None:
    assert "SELECT DISTINCT ON (t.transaction_id)" in sql(name)


def test_sweep_selects_the_count() -> None:
    assert "checked" in sql("fraud_card_sweep")


def test_sweep_keeps_the_count_when_nothing_is_flagged() -> None:
    # A one-row totals CTE, left-joined to the flagged set, returns a count-only
    # row for a clean card instead of no row at all (checked would read 0).
    text = sql("fraud_card_sweep")

    assert "SELECT COUNT(*) AS checked FROM window_tx" in text
    assert "FROM totals\nLEFT JOIN flagged AS f ON TRUE" in text


def test_sweep_flags_above_review_and_orders_by_score() -> None:
    text = sql("fraud_card_sweep")

    assert "WHERE fraud_score > %(review_above)s::numeric" in text
    assert (
        "ORDER BY fraud_score DESC, transaction_date DESC NULLS LAST, transaction_id"
        in text
    )
    # A join doesn't keep a CTE's order, so the outer select repeats it.
    assert "ORDER BY f.fraud_score DESC NULLS LAST" in text
    # The limit cuts the flagged set, never the count row.
    assert text.index("LIMIT %(limit)s") < text.index("FROM totals")


def test_sweep_window_is_thirty_days_up_to_as_of() -> None:
    text = sql("fraud_card_sweep")

    assert "t.transaction_date >= %(as_of)s - INTERVAL '30 days'" in text
    assert "t.transaction_date <= %(as_of)s" in text


def test_one_charge_is_bounded_by_as_of() -> None:
    assert "t.transaction_date <= %(as_of)s" in sql("fraud_transaction")


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "transaction_fraud_detection"
    assert spec["inputSchema"]["required"] == ["customer_id"]


def test_tool_spec_properties_match_the_request_fields() -> None:
    properties = set(tool_spec()["inputSchema"]["properties"])

    assert properties == {f.name for f in dataclasses.fields(FraudCheckRequest)}


def test_tool_spec_description_names_the_verdicts_and_the_window() -> None:
    description = tool_spec()["description"]

    for word in ("fraud", "review", "no_fraud", "not_scored", "checked", "30 days"):
        assert word in description, word
