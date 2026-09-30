"""Tests for FileQueryProvider: reading, caching and missing queries."""

from pathlib import Path

import pytest
from ledgerlens.application.ports.errors import QueryNotFoundError
from ledgerlens.infrastructure.queries.file_query_provider import FileQueryProvider

pytestmark = pytest.mark.unit


def test_reads_the_named_sql_file(tmp_path: Path) -> None:
    (tmp_path / "list_card_transactions.sql").write_text("SELECT 1", encoding="utf-8")

    assert FileQueryProvider(tmp_path).get("list_card_transactions") == "SELECT 1"


def test_caches_the_query_after_the_first_read(tmp_path: Path) -> None:
    path = tmp_path / "q.sql"
    path.write_text("SELECT 1", encoding="utf-8")
    provider = FileQueryProvider(tmp_path)

    provider.get("q")
    path.write_text("SELECT 2", encoding="utf-8")

    assert provider.get("q") == "SELECT 1"


def test_missing_file_raises_query_not_found(tmp_path: Path) -> None:
    with pytest.raises(QueryNotFoundError):
        FileQueryProvider(tmp_path).get("missing")


def test_empty_file_raises_query_not_found(tmp_path: Path) -> None:
    (tmp_path / "blank.sql").write_text("  \n", encoding="utf-8")

    with pytest.raises(QueryNotFoundError):
        FileQueryProvider(tmp_path).get("blank")


@pytest.mark.parametrize("name", ["../secrets", "a/b", "Q", "", "q.sql", "q;drop"])
def test_rejects_names_that_are_not_simple_identifiers(
    tmp_path: Path, name: str
) -> None:
    with pytest.raises(QueryNotFoundError):
        FileQueryProvider(tmp_path).get(name)
