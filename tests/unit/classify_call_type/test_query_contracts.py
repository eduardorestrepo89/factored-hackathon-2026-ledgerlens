"""Drift tests: the SQL files and tool_spec.json must match the Python contracts."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from classify_call_type_lambda.application.use_cases.classify_call_type import (
    QUERY_NAMES,
    ClassifyCallTypeUseCase,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason
from classify_call_type_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import (
    AS_OF,
    CUSTOMER_ID,
    FakeClassifyRepository,
    FakeQueryProvider,
    classify_responses,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/classify_call_type"
QUERIES_DIR = TOOL_ROOT / "classify_call_type_lambda/queries/postgresql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Crédito'"
NAMES = tuple(QUERY_NAMES.values())

# The columns each query must select: the ones the use case maps (Task 5).
SELECTED_COLUMNS = {
    "call_reason_transactions": (
        "transaction_id",
        "transaction_date",
        "card_last4",
        "card_currency",
        "merchant_name",
        "amount",
        "currency",
        "transaction_status",
        "response_code",
        "transaction_country",
        "home_country",
        "fraud_score",
    ),
    "call_reason_cards": (
        "card_last4",
        "product_status",
        "expiration_date",
        "days_past_due",
    ),
    "call_reason_cases": (
        "complaint_id",
        "case_type",
        "category",
        "subcategory",
        "status",
        "sla_breached",
        "days_open",
        "creation_date",
    ),
    "call_reason_app_events": ("event_id", "event_date", "page_title", "action"),
}


def sql(name: str) -> str:
    """Load one of the real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def sent_params() -> dict[str, dict[str, object]]:
    """Return the params the use case actually sends, keyed by query name."""
    database_repository = FakeClassifyRepository(classify_responses())
    use_case = ClassifyCallTypeUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    use_case.execute(CUSTOMER_ID, as_of=AS_OF)
    return dict(database_repository.calls)


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


# --- every query -------------------------------------------------------------


def test_the_folder_holds_exactly_the_four_queries() -> None:
    assert sorted(path.stem for path in QUERIES_DIR.glob("*.sql")) == sorted(NAMES)


def test_every_query_is_sent() -> None:
    assert set(sent_params()) == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == set(sent_params()[name])


@pytest.mark.parametrize("name", NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed.
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", NAMES)
def test_sql_sets_no_session_parameters(name: str) -> None:
    # DSQL rejects most session parameters (statement_timeout among them).
    text = sql(name)

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


@pytest.mark.parametrize("name", NAMES)
def test_no_query_reads_is_fraud(name: str) -> None:
    # DEC-10: the label is never read. Comments count too.
    assert "is_fraud" not in sql(name).lower()


@pytest.mark.parametrize(
    "name", [name for name in NAMES if name != "call_reason_transactions"]
)
def test_only_the_transactions_query_reads_the_score(name: str) -> None:
    assert "fraud_score" not in sql(name).lower()


@pytest.mark.parametrize("name", NAMES)
def test_each_query_checks_the_customer(name: str) -> None:
    assert "customer_id = %(customer_id)s" in sql(name)


@pytest.mark.parametrize("name", NAMES)
def test_sql_is_nfc_utf8_without_bom(name: str) -> None:
    # A decomposed accent or a BOM would silently match nothing.
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


@pytest.mark.parametrize("name", NAMES)
def test_sql_selects_every_column_the_use_case_maps(name: str) -> None:
    text = sql(name)
    for column in SELECTED_COLUMNS[name]:
        assert column in text, column


@pytest.mark.parametrize("name", ["call_reason_transactions", "call_reason_cards"])
def test_card_queries_are_credit_cards_only(name: str) -> None:
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert CREDIT_CARD_FILTER.encode("utf-8") in raw


# --- the transactions query --------------------------------------------------


def test_transactions_window_is_72_hours_plus_30_day_scored_charges() -> None:
    text = sql("call_reason_transactions")

    assert "SELECT DISTINCT ON (t.transaction_id)" in text
    assert "t.transaction_date >= %(as_of)s - INTERVAL '30 days'" in text
    assert "t.transaction_date <= %(as_of)s" in text
    assert "x.transaction_date >= %(as_of)s - INTERVAL '72 hours'" in text
    assert (
        "x.transaction_status = 'Approved' "
        "AND x.fraud_score > %(review_above)s::numeric"
    ) in text


def test_transactions_are_newest_first_and_capped() -> None:
    text = sql("call_reason_transactions")

    assert "ORDER BY x.transaction_date DESC NULLS LAST, x.transaction_id" in text
    assert text.rstrip().endswith("LIMIT %(limit)s")


def test_transactions_read_the_latest_home_country() -> None:
    text = sql("call_reason_transactions")

    assert "ORDER BY c.last_updated DESC NULLS LAST" in text
    assert "h.country AS home_country" in text


# --- the cards, cases and app events queries ----------------------------------


@pytest.mark.parametrize("name", ["call_reason_cards", "call_reason_cases"])
def test_cards_and_cases_have_no_limit(name: str) -> None:
    assert "LIMIT" not in sql(name)


def test_cards_are_deduplicated_to_the_latest_state() -> None:
    text = sql("call_reason_cards")

    assert "SELECT DISTINCT ON (p.product_id)" in text
    assert "ORDER BY p.product_id, p.last_updated DESC NULLS LAST" in text


def test_cases_select_their_creation_date_for_the_tie_break() -> None:
    # Spec 6.3: equal cases go to the newest, so the date must be selected,
    # not only filtered on.
    text = sql("call_reason_cases")
    select_list = text[text.index("SELECT deduplicated.") : text.index("FROM (")]
    items = [line.strip().rstrip(",") for line in select_list.splitlines()]

    # Its own column, not only inside the days_open expression.
    assert "deduplicated.creation_date" in items


def test_cases_are_the_ones_open_at_as_of() -> None:
    text = sql("call_reason_cases")

    assert "k.creation_date <= %(as_of)s" in text
    assert "k.closing_date > %(as_of)s" in text
    assert "k.status NOT IN ('Resolved', 'Closed')" in text
    assert "(%(as_of)s::date - deduplicated.creation_date::date) AS days_open" in text


def test_charges_in_an_open_claim_are_skipped() -> None:
    # open_claim writes "<statement> | tx: TRX-A,TRX-B"; a charge already claimed
    # is the claim's follow-up (OPEN_CASE_FOLLOWUP), not a new fraud reason.
    text = sql("call_reason_transactions")

    assert "AND NOT EXISTS (" in text
    assert "split_part(o.description, ' | tx: ', 2)" in text
    assert "',' || x.transaction_id || ','" in text
    # The same open-at-as_of filter and de-duplication as call_reason_cases.
    cases = sql("call_reason_cases")
    for line in (
        "SELECT DISTINCT ON (k.complaint_id)",
        "FROM complaints AS k",
        "WHERE k.customer_id = %(customer_id)s",
        "AND k.creation_date <= %(as_of)s",
        "AND (k.closing_date > %(as_of)s",
        "OR (k.closing_date IS NULL AND k.status NOT IN ('Resolved', 'Closed')))",
        "ORDER BY k.complaint_id, k.process_date DESC NULLS LAST",
    ):
        assert line in cases, line
        assert line in text, line


def test_app_events_are_errors_of_the_last_24_hours() -> None:
    text = sql("call_reason_app_events")

    assert "e.event_type = 'Error'" in text
    assert "e.event_date >  %(as_of)s - INTERVAL '24 hours'" in text
    assert "e.event_date <= %(as_of)s" in text
    assert text.rstrip().endswith("LIMIT 50")


# --- tool_spec.json ------------------------------------------------------------


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "classify_call_type"
    assert spec["inputSchema"]["required"] == ["customer_id"]
    assert set(spec["inputSchema"]["properties"]) == {"customer_id"}
    assert spec["inputSchema"]["properties"]["customer_id"]["type"] == "string"


def test_tool_spec_description_names_every_reason() -> None:
    description = tool_spec()["description"]

    for reason in CallReason:
        assert reason.value in description, reason
    assert "unavailable" in description


def test_tool_spec_description_says_it_already_ran_at_session_start() -> None:
    # The agent calls it in code at session start (tools/session_context.py);
    # telling the model to call it first would repeat the call on turn one.
    description = tool_spec()["description"]

    assert "Already called automatically at session start" in description
    assert "Call it at the start of the conversation" not in description
