"""QueryProvider adapter that reads ``<name>.sql`` files from a dialect folder."""

import re
from pathlib import Path
from typing import Final

from classify_call_type_lambda.application.ports.errors import QueryNotFoundError
from classify_call_type_lambda.application.ports.query_provider import QueryProvider

# Only simple identifiers: blocks path traversal such as "../secrets".
_QUERY_NAME: Final = re.compile(r"[a-z0-9_]+")


class FileQueryProvider(QueryProvider):
    """Load SQL text from ``<directory>/<name>.sql`` and cache it per instance.

    Files ship inside the Lambda asset and never change at runtime, so each file
    is read at most once per container.
    """

    def __init__(self, directory: Path) -> None:
        """Serve queries from ``directory`` (one folder per SQL dialect)."""
        self._directory: Path = directory
        self._cache: dict[str, str] = {}

    def get(self, name: str) -> str:
        """Return the SQL text of the named query.

        Raises:
            QueryNotFoundError: The name is invalid, or the file is missing,
                unreadable or empty.
        """
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        if not _QUERY_NAME.fullmatch(name):
            raise QueryNotFoundError(f"Invalid query name: {name!r}")
        path = self._directory / f"{name}.sql"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise QueryNotFoundError(f"Query {name!r} not found at {path}") from exc
        if not text.strip():
            raise QueryNotFoundError(f"Query {name!r} at {path} is empty")
        self._cache[name] = text
        return text
