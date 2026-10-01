"""Drift tests: the SQL file and tool_spec.json must match the Python contracts."""

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest
from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.domain.value_objects.transaction_filters import (
    TransactionFilters,
    TransactionStatus,
)
from ledgerlens.infrastructure.queries.file_query_provider import FileQueryProvider
from ledgerlens_fakes import FakeDatabaseRepository, FakeQueryProvider, make_filters

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
QUERIES_DIR = REPO_ROOT / "gateway/tools/ledgerlens_tools/ledgerlens/queries/postgresql"
TOOL_SPEC = REPO_ROOT / "gateway/tools/list_card_transactions/tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")


def sql() -> str:
    """Load the real list_card_transactions query."""
    return FileQueryProvider(QUERIES_DIR).get("list_card_transactions")


def sent_params() -> dict[str, object]:
    """Return the params the use case actually sends to the database repository."""
    database_repository = FakeDatabaseRepository()
    ListCardTransactionsUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    ).execute(make_filters())
    return database_repository.calls[0][1]


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_sql_placeholders_match_the_use_case_params_exactly() -> None:
    assert set(PLACEHOLDER.findall(sql())) == set(sent_params())


def test_sql_has_no_stray_percent_signs() -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed.
    assert "%" not in PLACEHOLDER.sub("", sql())


def test_sql_orders_null_transaction_dates_last() -> None:
    # PostgreSQL sorts NULLs first under DESC; a NULL-dated row would then
    # always land inside LIMIT and fail the whole call as DataIntegrityError.
    order_bys = re.findall(r"ORDER BY[^\n]*", sql())
    assert len(order_bys) == 2
    for order_by in order_bys:
        assert "transaction_date DESC NULLS LAST" in order_by


def test_sql_selects_every_column_the_use_case_maps() -> None:
    text = sql()
    for column in (
        "transaction_id",
        "transaction_date",
        "card_last4",
        "amount",
        "currency",
        "transaction_status",
        "merchant_name",
        "merchant_category",
        "channel",
        "transaction_city",
        "transaction_country",
    ):
        assert column in text


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "list_card_transactions"
    assert spec["inputSchema"]["required"] == ["customer_id"]


def test_tool_spec_properties_match_the_filter_fields() -> None:
    properties = set(tool_spec()["inputSchema"]["properties"])

    assert properties == {f.name for f in dataclasses.fields(TransactionFilters)}


def test_tool_spec_status_enum_matches_the_domain_enum() -> None:
    status = tool_spec()["inputSchema"]["properties"]["status"]

    assert status["enum"] == [s.value for s in TransactionStatus]
