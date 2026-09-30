"""Dependency builder for the list_card_transactions tool."""

from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.delivery.database import build_query_provider, build_repository
from ledgerlens.delivery.settings import DatabaseSettings
from ledgerlens.utils.connectors.base import PsycopgConnector


def build_dependencies(
    connector: PsycopgConnector, settings: DatabaseSettings
) -> ListCardTransactionsUseCase:
    """Wire the use case around the global connector.

    Cheap to call on every invocation: it only builds plain objects. The
    connection lives in the connector, and SQL text is cached by the provider.
    """
    return ListCardTransactionsUseCase(
        repository=build_repository(settings.engine, connector),
        queries=build_query_provider(settings.engine),
        max_rows=settings.max_rows,
    )
