"""Use case: open fraud or dispute claims for some of a customer's card transactions."""

import base64
import hashlib
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from open_claim_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from open_claim_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    WriteConflictError,
)
from open_claim_lambda.application.ports.query_provider import QueryProvider
from open_claim_lambda.domain.entities.claim import (
    Claim,
    ClaimsResult,
    ResolutionEstimate,
)
from open_claim_lambda.domain.errors import (
    ClaimDataIntegrityError,
    ClaimError,
    DataSourceUnavailableError,
    InvalidInputError,
    TransactionsNotFoundError,
)

logger = logging.getLogger(__name__)

# complaints.subcategory values in the dataset, by claim type.
SUBCATEGORIES: Final[Mapping[str, str]] = {
    "fraud": "Cargo no reconocido",
    "dispute": "Cobro indebido",
}
OPEN: Final = "Open"
MAX_TRANSACTIONS: Final = 10
MAX_TRANSACTION_ID_LENGTH: Final = 30  # transactions.transaction_id is varchar(30)
MAX_STATEMENT_LENGTH: Final = 500
# Above this total in USD a claim is High priority: the fraud protocol's hand-off line.
HIGH_PRIORITY_USD: Final = Decimal("500")
ESTIMATE_WINDOW: Final = timedelta(days=365)


@dataclass(frozen=True)
class _Charge:
    """One disputed transaction, as claim_transactions returns it."""

    transaction_id: str
    product_id: str
    card_last4: str
    amount: Decimal
    currency: str
    amount_usd: Decimal | None


class OpenClaimUseCase:
    """Open one claim per card and currency through a database-agnostic repository.

    Each claim's id is derived from its content, so the same request run twice (a
    retry, or the model calling again) finds the existing claim instead of
    opening a second one. The resolution estimate is best effort: once a claim
    is written, nothing after it may turn the call into an error.
    """

    TRANSACTIONS_QUERY: Final = "claim_transactions"
    INSERT_QUERY: Final = "insert_claim"
    ESTIMATE_QUERY: Final = "resolution_estimate"

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
    ) -> None:
        """Store the ports."""
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider

    def execute(
        self,
        customer_id: object,
        transaction_ids: object,
        claim_type: object,
        customer_statement: object,
        customer_confirmed: object,
        now: datetime,
    ) -> ClaimsResult:
        """Validate every input, then open the claims and estimate their duration.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            transaction_ids: 1 to 10 transaction ids, as they came.
            claim_type: fraud or dispute, as it came.
            customer_statement: The customer's words, as they came.
            customer_confirmed: Must be the boolean True.
            now: The tool's "now" (AS_OF in demos), the claims' creation date.

        Raises:
            InvalidInputError: An input is invalid, or customer_confirmed isn't
                true. Raised before the database is touched.
            TransactionsNotFoundError: Some ids aren't the customer's credit card
                transactions. Raised before any claim is written.
            DataSourceUnavailableError: The database can't be reached, or kept
                reporting write conflicts.
            ClaimError: A query failed.
            ClaimDataIntegrityError: A returned row couldn't be read.
        """
        customer = _clean_customer_id(customer_id)
        ids = _clean_transaction_ids(transaction_ids)
        kind = _clean_claim_type(claim_type)
        statement = _clean_statement(customer_statement)
        _require_confirmation(customer_confirmed)
        created = _naive_utc(now)
        try:
            rows = self._run(
                self.TRANSACTIONS_QUERY,
                {"customer_id": customer, "transaction_ids": list(ids)},
            )
            claims = tuple(
                self._open(customer, kind, statement, created, group)
                for group in _groups(_charges(rows, ids))
            )
        except (DataSourceConnectionError, WriteConflictError) as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise ClaimError() from exc
        return ClaimsResult(
            claims=claims,
            resolution_estimate=self._estimate(SUBCATEGORIES[kind], created),
        )

    def _open(
        self,
        customer_id: str,
        claim_type: str,
        statement: str,
        created: datetime,
        group: Sequence[_Charge],
    ) -> Claim:
        """Insert one claim, or find that the same claim already exists."""
        first = group[0]
        ids = tuple(charge.transaction_id for charge in group)
        claim_id = claim_id_for(
            customer_id, claim_type, first.product_id, first.currency, ids
        )
        amount = sum((charge.amount for charge in group), Decimal(0))
        priority = _priority(group)
        try:
            self._run(
                self.INSERT_QUERY,
                {
                    "complaint_id": claim_id,
                    "creation_date": created,
                    "process_date": created.date(),
                    "customer_id": customer_id,
                    "subcategory": SUBCATEGORIES[claim_type],
                    "product_id": first.product_id,
                    "description": f"{statement} | tx: {','.join(ids)}",
                    "claimed_amount": amount,
                    "currency": first.currency,
                    "priority": priority,
                },
            )
            already_existed = False
        except DuplicateKeyError:
            # The same request ran before: a retry, or the model calling again.
            already_existed = True
        return Claim(
            claim_id=claim_id,
            card_last4=first.card_last4,
            transaction_ids=ids,
            claimed_amount=amount,
            currency=first.currency,
            priority=priority,
            status=OPEN,
            already_existed=already_existed,
        )

    def _estimate(
        self, subcategory: str, created: datetime
    ) -> ResolutionEstimate | None:
        """Median and p90 resolution days of similar past claims; None when unknown.

        The claims are already written, so any failure here is logged, never
        raised.
        """
        try:
            rows = self._run(
                self.ESTIMATE_QUERY,
                {"subcategory": subcategory, "since": created - ESTIMATE_WINDOW},
            )
            if not rows:
                return None
            return ResolutionEstimate(
                median_days=_days(rows[0], "median_days"),
                p90_days=_days(rows[0], "p90_days"),
            )
        except (DataAccessError, KeyError, TypeError, ValueError):
            logger.warning(
                "Resolution estimate failed; the claims stay open without it",
                exc_info=True,
            )
            return None

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it."""
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)


def claim_id_for(
    customer_id: str,
    claim_type: str,
    product_id: str,
    currency: str,
    transaction_ids: Sequence[str],
) -> str:
    """Return the claim's id: ``CMP-`` and 20 base32 characters of a content hash.

    The same customer, type, card, currency and transactions (in any order)
    always give the same id, so the primary key refuses a second claim for them.
    """
    key = "|".join(
        (
            customer_id,
            claim_type,
            product_id,
            currency,
            ",".join(sorted(transaction_ids)),
        )
    )
    digest = base64.b32encode(hashlib.sha256(key.encode("utf-8")).digest())
    return f"CMP-{digest.decode('ascii')[:20]}"


def _charges(rows: Sequence[Mapping[str, Any]], ids: Sequence[str]) -> list[_Charge]:
    """Map the rows, check every requested id came back, order them as requested.

    Raises:
        ClaimDataIntegrityError: A row couldn't be read.
        TransactionsNotFoundError: Some ids aren't the customer's credit card
            transactions.
    """
    try:
        found = {charge.transaction_id: charge for charge in map(_to_charge, rows)}
    except (KeyError, TypeError, ValueError) as exc:
        raise ClaimDataIntegrityError() from exc
    missing = [i for i in ids if i not in found]
    if missing:
        raise TransactionsNotFoundError(missing)
    return [found[i] for i in ids]


def _groups(charges: Sequence[_Charge]) -> list[list[_Charge]]:
    """Group by card and currency, one claim each, ordered by card then currency."""
    groups: dict[tuple[str, str], list[_Charge]] = {}
    for charge in charges:
        groups.setdefault((charge.product_id, charge.currency), []).append(charge)
    return sorted(
        groups.values(), key=lambda g: (g[0].card_last4, g[0].currency, g[0].product_id)
    )


def _priority(group: Sequence[_Charge]) -> str:
    """High when the total in USD is unknown or above HIGH_PRIORITY_USD."""
    known = [c.amount_usd for c in group if c.amount_usd is not None]
    if len(known) < len(group) or sum(known, Decimal(0)) > HIGH_PRIORITY_USD:
        return "High"
    return "Medium"


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return raw.strip().upper()


def _clean_transaction_ids(raw: object) -> tuple[str, ...]:
    """Strip, uppercase and de-duplicate 1 to MAX_TRANSACTIONS ids, keeping order.

    Raises:
        InvalidInputError: Not a list, empty, an item isn't a non-empty string of
            at most 30 characters, or more than 10 distinct ids.
    """
    reason = (
        f"must be a list of 1 to {MAX_TRANSACTIONS} transaction ids "
        "from list_card_transactions"
    )
    if not isinstance(raw, list) or not raw:
        raise InvalidInputError("transaction_ids", reason)
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise InvalidInputError("transaction_ids", reason)
        clean = item.strip().upper()
        if not clean or len(clean) > MAX_TRANSACTION_ID_LENGTH:
            raise InvalidInputError("transaction_ids", reason)
        if clean not in ids:
            ids.append(clean)
    if len(ids) > MAX_TRANSACTIONS:
        raise InvalidInputError("transaction_ids", reason)
    return tuple(ids)


def _clean_claim_type(raw: object) -> str:
    """Strip and lowercase the type; it must be fraud or dispute.

    Raises:
        InvalidInputError: Anything else.
    """
    if isinstance(raw, str) and raw.strip().lower() in SUBCATEGORIES:
        return raw.strip().lower()
    raise InvalidInputError("claim_type", "must be fraud or dispute")


def _clean_statement(raw: object) -> str:
    """Strip the customer's words; 1 to MAX_STATEMENT_LENGTH characters.

    Raises:
        InvalidInputError: Not a string, blank or too long.
    """
    reason = f"must be the customer's own words, 1 to {MAX_STATEMENT_LENGTH} characters"
    if not isinstance(raw, str):
        raise InvalidInputError("customer_statement", reason)
    statement = raw.strip()
    if not statement or len(statement) > MAX_STATEMENT_LENGTH:
        raise InvalidInputError("customer_statement", reason)
    return statement


def _require_confirmation(raw: object) -> None:
    """Only the boolean True confirms; "true", 1 or a missing value don't.

    The Gateway's Cedar statement 3 will check it too (spec section 10).

    Raises:
        InvalidInputError: The value isn't True.
    """
    if raw is not True:
        raise InvalidInputError(
            "customer_confirmed",
            "must be true, after the customer explicitly confirmed these transactions",
        )


def _naive_utc(now: datetime) -> datetime:
    """Return ``now`` as naive UTC: complaints.creation_date has no time zone."""
    if now.tzinfo is None:
        return now
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def _to_charge(row: Mapping[str, Any]) -> _Charge:
    """Map one claim_transactions row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type.
        ValueError: An amount isn't finite.
    """
    return _Charge(
        transaction_id=_text(row, "transaction_id"),
        product_id=_text(row, "product_id"),
        card_last4=_text(row, "card_last4"),
        amount=_amount(row, "amount"),
        currency=_text(row, "currency"),
        amount_usd=None if row["amount_usd"] is None else _amount(row, "amount_usd"),
    )


def _text(row: Mapping[str, Any], column: str) -> str:
    """Return a non-empty text column."""
    value = row[column]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{column} is {type(value).__name__}, expected text")
    return value


def _amount(row: Mapping[str, Any], column: str) -> Decimal:
    """Return a finite numeric column as an exact Decimal; bool is rejected."""
    value = row[column]
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise TypeError(f"{column} is {type(value).__name__}, expected a number")
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"{column} is not finite")
    return amount


def _days(row: Mapping[str, Any], column: str) -> int:
    """Round a finite day count up to whole days."""
    value = row[column]
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise TypeError(f"{column} is {type(value).__name__}, expected a number")
    if not math.isfinite(value):
        raise ValueError(f"{column} is not finite")
    return math.ceil(value)
