# `get_session_context` Lambda: Design

**Date:** 2026-10-01
**Status:** Approved 2026-10-01.
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §6 and §7.1
**Layout rules:** [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md). One folder per tool, wrapping every layer. Code is copied between tools, never shared.
**Copied from:** `gateway/tools/list_credit_cards/` (see §8).

---

## 1. Goal

This spec covers two pieces of work:

1. **`AS_OF` in every tool.** Each tool Lambda reads an optional `AS_OF` environment variable and treats it as "now". Demos can then run against the historical dataset on any date. Production leaves it unset.
2. **The `get_session_context` tool.** It returns one compact snapshot of the customer at session start:
   - profile
   - credit cards
   - card transactions from the last 72 hours, with risk flags
   - app/web signals from the last 24 hours
   - cases open at `as_of`

   The agent code calls it before the model runs (product design §6). The model can also call it to refresh.

### Success criteria
- `list_card_transactions` and `get_session_context` count every time window from `AS_OF` when it's set, and from the real UTC time when it isn't.
- `list_credit_cards` parses `AS_OF` the same way. It has no time window, so the setting isn't used there yet.
- `get_session_context` returns the JSON in §4.5. A section that fails comes back `null` and is listed in `unavailable`; the other sections are still returned.
- The whole call only fails when the customer section fails. It then returns one fixed message that shows no internals.
- The §7 conventions hold: row caps, amounts as 2-decimal strings, card numbers only as `last4`, no sensitive customer fields, and transactions de-duplicated.
- Unit tests cover every layer with no database or AWS. The three tools' tests run together in one pytest session.
- `ruff format --check` and `ruff check` are clean. Nothing imports across tool folders.

### Decisions made with the user
| Topic | Decision |
|---|---|
| "Now" | Optional `AS_OF` env var in **every** tool Lambda. Unset means the real UTC time. It's never a tool input, so the model can't change it. |
| Failures | **Partial snapshot.** A failed section is `null` and is listed in `unavailable`. Only a customer-section failure fails the call. |
| Execution | The five queries run **one after another** on the tool's single autocommit connection. There's no connection pool or thread. |
| `transaction_status` values | `Approved`, `Declined`, `Pending`, `Reversed` (confirmed by the user). |
| `page_title`, `event_type`, `action` values | Confirmed by the user; the signal rules in §5.4 use them exactly. |

### Out of scope
- CDK: no Lambda, Gateway target, grants or `AS_OF` wiring yet (R1).
- The agent's session-start call (product design §6, `call_tool_sync`).
- `classify_call_type` and every other tool.
- `language_hint` from §7.1's output. `customers` has no language column (Q6), and the model can infer the language from `country`.
- Running the five queries in parallel. If latency on a real cluster requires it, that's a later change behind the same use case.

---

## 2. Task 1: `AS_OF` in every tool

### 2.1 Settings (`delivery/settings.py`, in each of the three tools)

```python
@dataclass(frozen=True)
class ClockSettings:
    """The tool's notion of "now".

    Attributes:
        as_of: Fixed UTC "now" from AS_OF, or None to use the real clock.
    """

    as_of: datetime | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ClockSettings": ...

    def now(self) -> datetime:
        """Return as_of when set, else datetime.now(timezone.utc). Always aware UTC."""
```

How `from_env` parses `AS_OF` (in a private `_as_of(env)` helper):

| `AS_OF` | Result |
|---|---|
| missing or blank | `None` (real clock) |
| `2026-03-14` | `2026-03-14T00:00:00+00:00` |
| `2026-03-14T10:30:00` (naive) | Treated as UTC |
| `2026-03-14T10:30:00-05:00` | Converted to UTC: `15:30:00+00:00` |
| `2026-03-14T10:30:00Z` | UTC |
| anything else (`yesterday`, `2026-13-01`) | `ConfigurationError("AS_OF must be an ISO 8601 date or timestamp, got ...")` |

Python 3.13's `datetime.fromisoformat` accepts all the valid forms above, including `Z` and a bare date.

### 2.2 Builder (`delivery/dependencies/dependencies_builder.py`, in each tool)

A new block between Settings and Connection:

```python
def build_clock(env: Mapping[str, str]) -> ClockSettings | None:
    """Read AS_OF. Never raises.

    Returns:
        The clock settings, or None when AS_OF is invalid. Every request then
        gets DataSourceUnavailableError's message.
    """
```

An invalid `AS_OF` is logged with `logger.exception("Invalid AS_OF for <tool>")`.

### 2.3 Handlers

- **Every handler** gets `CLOCK = build_clock(os.environ)` at module level, next to `USE_CASE`. Inside the `try`, the `None` guard becomes `if USE_CASE is None or CLOCK is None: raise DataSourceUnavailableError()`. "Now" is read on every call with `CLOCK.now()`, never at load time, so a warm container doesn't freeze the real clock.
- **`list_card_transactions`:** `TransactionFilters.from_raw(event, today=CLOCK.now().date())` replaces `datetime.now(timezone.utc).date()`.
- **`list_credit_cards`:** it has the guard but doesn't call `CLOCK.now()`, because it has no time window. An invalid `AS_OF` still makes it answer with the unavailable message, the same as any other bad setting. That keeps the three tools consistent.
- **`get_session_context`:** `USE_CASE.execute(customer_id, as_of=CLOCK.now())`.

---

## 3. Layout (Task 2 onwards)

```
gateway/tools/get_session_context/                   ← Lambda asset root for this tool only
├── tool_spec.json
├── requirements.txt                                 (copy)
└── get_session_context_lambda/
    ├── __init__.py
    ├── domain/
    │   ├── entities/session_context.py              Customer, CreditCard, RecentTransaction,
    │   │                                            DigitalSignal, OpenCase, SessionContext
    │   └── errors.py                                session-context domain errors
    ├── application/
    │   ├── ports/{database_repository,query_provider,errors}.py   (copy)
    │   └── use_cases/get_session_context.py         GetSessionContextUseCase + mapping helpers
    ├── infrastructure/
    │   ├── queries/file_query_provider.py           (copy)
    │   └── repositories/dsql_repository.py          (copy)
    ├── utils/connectors/{base,dsql}.py              (copy)
    ├── delivery/
    │   ├── handler.py
    │   ├── settings.py                              (copy, with ClockSettings)
    │   ├── dependencies/dependencies_builder.py     build_get_session_context_use_case, build_clock
    │   └── presenters/session_context.py            present_session_context
    └── queries/postgresql/
        ├── session_customer_profile.sql
        ├── session_credit_cards.sql
        ├── session_recent_transactions.sql
        ├── session_digital_signals.sql
        └── session_open_cases.sql

tests/unit/get_session_context/                      ← package (has __init__.py)
├── __init__.py, conftest.py, fakes.py
└── test_*.py
```

- **Handler string:** `get_session_context_lambda/delivery/handler.handler`.
- **Tool name:** `get_session_context`.
- **Gateway target, for the CDK spec later:** `get-session-context-target`.

---

## 4. Contracts

### 4.1 Input
The bare `customer_id`, handled exactly as in `list_credit_cards`:
- The handler passes `event.get("customer_id")` when the event is a JSON object, and `None` otherwise.
- The use case's `_clean_customer_id` strips it and uppercases it.
- A value that isn't a string, or is blank, raises `InvalidInputError("customer_id", "is required and must be a non-empty string")` before the database is touched.
- Unknown keys are ignored.

### 4.2 `as_of`
- `execute(customer_id, as_of)` takes an **aware** datetime. A naive one raises `ValueError`; that's a programming error, not user input.
- The use case converts it to UTC and drops the time zone before binding it (`as_of_sql`), because the ERD's columns are `timestamp` without a time zone.
- Every query gets the same `as_of_sql`.

### 4.3 Entities (`domain/entities/session_context.py`)
Every field is nullable, because the ERD notes about 5% nulls in nullable fields.

```python
@dataclass(frozen=True)
class Customer:
    customer_id: str          # never None: it's the row's key
    first_name: str | None
    country: str | None
    city: str | None
    customer_status: str | None

@dataclass(frozen=True)
class CreditCard:             # same 8 fields as list_credit_cards (copied)
    card_last4: str | None
    product_status: str | None
    currency: str | None
    current_balance: Decimal | None
    credit_limit: Decimal | None
    available_credit: Decimal | None
    expiration_date: date | None
    days_past_due: int | None

class TransactionFlag(str, Enum):  # declared in output order
    DECLINED = "declined"
    FOREIGN = "foreign"
    ABOVE_USUAL_AMOUNT = "above_usual_amount"
    NEW_MERCHANT = "new_merchant"

@dataclass(frozen=True)
class RecentTransaction:
    transaction_id: str | None
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    transaction_country: str | None
    flags: tuple[TransactionFlag, ...]   # only the true ones, in enum order

@dataclass(frozen=True)
class DigitalSignal:
    event_date: datetime | None
    signal: str                          # never None: rows without a signal are filtered in SQL
    page_title: str | None
    ip_country: str | None
    ip_city: str | None

@dataclass(frozen=True)
class OpenCase:
    complaint_id: str | None
    case_type: str | None
    category: str | None
    subcategory: str | None
    status: str | None
    priority: str | None
    sla_breached: bool | None
    claimed_amount: Decimal | None
    currency: str | None
    days_open: int | None

class Section(str, Enum):            # declared in output order
    CARDS = "cards"
    RECENT_TRANSACTIONS = "recent_transactions"
    DIGITAL_SIGNALS = "digital_signals"
    OPEN_CASES = "open_cases"

@dataclass(frozen=True)
class SessionContext:
    as_of: datetime                                     # aware UTC
    customer: Customer
    cards: tuple[CreditCard, ...] | None                # None = unavailable
    recent_transactions: tuple[RecentTransaction, ...] | None
    digital_signals: tuple[DigitalSignal, ...] | None
    open_cases: tuple[OpenCase, ...] | None
    truncated: tuple[Section, ...]                      # in enum order
    unavailable: tuple[Section, ...]                    # in enum order
```

- **Flags:** the SQL returns them as four boolean columns. A `NULL` comparison (an unknown country, for example) maps to "not flagged". Any non-bool value other than `None` raises `TypeError`.
- **`signal`:** a plain string, not an enum. The SQL owns the mapping in §5.4, and the contract test pins the four values.

### 4.4 Use case (`application/use_cases/get_session_context.py`)

```python
class GetSessionContextUseCase:
    OPEN_CASES_CAP: Final = 5

    def __init__(self, database_repository, query_provider, max_rows: int = 25): ...
    def execute(self, customer_id: object, as_of: datetime) -> SessionContext: ...
```

- `max_rows < 1` raises `ValueError`.
- Cards, transactions and signals are capped at `max_rows`. Open cases are capped at `min(OPEN_CASES_CAP, max_rows)`.
- Each section's query gets `limit = cap + 1`. A section is listed in `truncated` when the extra row comes back.

**Order inside `execute`:**
1. Clean `customer_id` and check that `as_of` is aware.
2. **Customer section** (`session_customer_profile`, params `customer_id`). This section is the core:
   - `DataSourceConnectionError` → `DataSourceUnavailableError`
   - any other `DataAccessError` → `SessionContextLookupError`
   - no row → `CustomerNotFoundError`
   - a mapping error (`KeyError`, `TypeError`, `ValueError`) → `SessionContextDataIntegrityError`
3. **The other four sections, in `Section` order.** Each one runs in its own `try`. Any `DataAccessError` or mapping error makes the section `None`, adds it to `unavailable`, and logs `logger.warning("get_session_context section %s unavailable", section.value, exc_info=True)`. The next section still runs.
   - `DataSourceConnectionError` here doesn't stop the rest. The repository already retried once, and the next section's query reconnects lazily. If the database is really gone, every section fails quickly on the connection and the result lists all four.

**Parameters each query gets** (every key must match a placeholder, and vice versa):

| Query | Params |
|---|---|
| `session_customer_profile` | `customer_id` |
| `session_credit_cards` | `customer_id`, `limit` |
| `session_recent_transactions` | `customer_id`, `as_of`, `limit` |
| `session_digital_signals` | `customer_id`, `as_of`, `limit` |
| `session_open_cases` | `customer_id`, `as_of`, `limit` |

The mapping helpers stay at the bottom of the module, as in `list_credit_cards`:
- copied: `_clean_customer_id`, `_optional_text`, `_optional_amount`, `_optional_date`, `_optional_int`
- new:
  - `_optional_datetime`: a `datetime` is kept; anything else raises `TypeError`
  - `_optional_bool`: only `bool` or `None`
  - `_required_text`: used for `customer_id` and `signal`; `None` raises `TypeError`
  - `_flags`
  - one `_to_<entity>` per entity

### 4.5 Output to the agent (`delivery/presenters/session_context.py`)

`present_session_context(context)` returns:

```json
{
  "as_of": "2026-03-14T12:00:00Z",
  "customer": {
    "customer_id": "CLI-F2DZJYU0POJ9",
    "first_name": "Ana",
    "country": "CO",
    "city": "Bogotá",
    "customer_status": "Active"
  },
  "cards": [
    {
      "card_last4": "4821",
      "product_status": "Active",
      "currency": "COP",
      "current_balance": "1250000.00",
      "credit_limit": "3000000.00",
      "available_credit": "1750000.00",
      "expiration_date": "2027-03-31",
      "days_past_due": 0
    }
  ],
  "recent_transactions": [
    {
      "transaction_id": "TX-1",
      "transaction_date": "2026-03-14T10:42:00",
      "card_last4": "4821",
      "merchant_name": "EXITO",
      "amount": "350000.00",
      "currency": "COP",
      "transaction_status": "Declined",
      "transaction_country": "CO",
      "flags": ["declined", "above_usual_amount"]
    }
  ],
  "digital_signals": [
    {
      "event_date": "2026-03-14T10:48:00",
      "signal": "FAILED_ACTION",
      "page_title": "Tarjeta de Crédito",
      "ip_country": "CO",
      "ip_city": "Bogotá"
    }
  ],
  "open_cases": [
    {
      "complaint_id": "C-1182",
      "case_type": "Claim",
      "category": "Cards",
      "subcategory": "Unrecognized charge",
      "status": "In progress",
      "priority": "High",
      "sla_breached": false,
      "claimed_amount": "350000.00",
      "currency": "COP",
      "days_open": 3
    }
  ],
  "truncated": [],
  "unavailable": []
}
```

- `as_of` is ISO in UTC with a `Z`.
- Row timestamps are ISO **without** a time zone, as stored. Dates are `YYYY-MM-DD`.
- Amounts are rounded half-up to strings with 2 decimals. `days_past_due` and `days_open` stay integers, and `sla_breached` stays a bool.
- `None` becomes JSON `null`.
- **An empty section is `[]`** (for example, no recent transactions). **A failed section is `null`** and its name is in `unavailable`. This is different from `list_credit_cards`, where `"cards": null` means "no cards". Here `null` has to mean "couldn't load", so "none" can't use it too. `truncated` and `unavailable` are always lists, possibly empty.

### 4.6 `tool_spec.json`

```json
[
  {
    "name": "get_session_context",
    "description": "Returns a snapshot of the customer: profile, credit cards, card transactions from the last 72 hours with risk flags (declined, foreign, above_usual_amount, new_merchant), app/web signals from the last 24 hours (FAILED_ACTION, REVIEWING_TRANSACTIONS, VIEWING_CREDIT_CARD, SEEKING_HELP) and open cases. Already called automatically at session start; call again only if the customer asks you to refresh or more than 30 minutes have passed. Lists hold at most 25 items (5 open cases). An empty list means there is nothing; a null section couldn't be loaded and is named in 'unavailable'. 'truncated' names lists that had more items. Amounts are strings with 2 decimals in the given currency.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's ID from SESSION CONTEXT."
        }
      },
      "required": ["customer_id"]
    }
  }
]
```

---

## 5. SQL (`queries/postgresql/`)

Every file starts with a header comment in the style of the other tools: its parameters, the reasons for its choices, and the `R3`/`R8` TODO tags. None of the files contains a literal `%`. Every string literal is in the file as UTF-8, and the connection uses `client_encoding=utf8`.

### 5.1 `session_customer_profile.sql`
```sql
SELECT DISTINCT ON (c.customer_id)
       c.customer_id,
       c.first_name,
       c.country,
       c.city,
       c.customer_status
FROM customers AS c
WHERE c.customer_id = %(customer_id)s
ORDER BY c.customer_id, c.last_updated DESC NULLS LAST
```
- Sensitive columns (credit score, income, gender, date of birth and others) are deliberately not selected.
- `DISTINCT ON` keeps the latest copy if the row is duplicated (R8).

### 5.2 `session_credit_cards.sql`
The same SQL as `list_credit_cards.sql` (copied): credit cards only (`'Tarjeta Crédito'`), every status, de-duplicated on `product_id`, active first, `LIMIT %(limit)s`.

### 5.3 `session_recent_transactions.sql`
```sql
WITH tx_dedup AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.transaction_date, t.product_id,
           t.merchant_name, t.amount, t.currency, t.amount_usd,
           t.transaction_status, t.transaction_country,
           RIGHT(p.product_number, 4) AS card_last4
    FROM transactions AS t
    JOIN products AS p ON p.product_id = t.product_id
    WHERE t.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
      AND t.process_date >= (%(as_of)s::date - 90)
      AND t.transaction_date <= %(as_of)s
    ORDER BY t.transaction_id, t.transaction_date DESC
),
recent AS (
    SELECT * FROM tx_dedup
    WHERE transaction_date >= %(as_of)s - INTERVAL '72 hours'
),
hist AS (
    SELECT * FROM tx_dedup
    WHERE transaction_date < %(as_of)s - INTERVAL '72 hours'
),
baseline AS (
    SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY amount_usd) AS p95_usd
    FROM hist
    WHERE transaction_status = 'Approved'
),
home AS (
    SELECT c.country
    FROM customers AS c
    WHERE c.customer_id = %(customer_id)s
    ORDER BY c.last_updated DESC NULLS LAST
    LIMIT 1
)
SELECT r.transaction_id,
       r.transaction_date,
       r.card_last4,
       r.merchant_name,
       r.amount,
       r.currency,
       r.transaction_status,
       r.transaction_country,
       (r.transaction_status = 'Declined')                       AS is_declined,
       (r.transaction_country <> h.country)                      AS is_foreign,
       (r.amount_usd > COALESCE(b.p95_usd, 'Infinity'))          AS is_above_usual_amount,
       (r.merchant_name IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM hist AS x
                        WHERE x.merchant_name = r.merchant_name)) AS is_new_merchant
FROM recent AS r
LEFT JOIN home AS h ON TRUE
CROSS JOIN baseline AS b
ORDER BY r.transaction_date DESC NULLS LAST, r.transaction_id
LIMIT %(limit)s
```
- **Credit-card transactions only.** That way `card_last4` always matches a card in `cards`, and the baseline compares like with like.
- **`declined`** is `= 'Declined'`. `Pending` and `Reversed` aren't declines; the model sees them in `transaction_status`.
- **Baseline:** the 95th percentile of approved USD amounts in the 90 days before the 72-hour window. With no history it's `Infinity`, so nothing is flagged.
- **`new_merchant`:** a merchant not seen in that history. A null merchant is never "new".
- **`LEFT JOIN home`:** a missing customer row gives `NULL` → not foreign, instead of losing every row. (`CROSS JOIN baseline` is safe because an aggregate always returns one row.)
- `process_date >= as_of::date - 90` is there for partition pruning, as in product design §8.1.

### 5.4 `session_digital_signals.sql`
```sql
SELECT signals.*
FROM (
    SELECT e.event_date,
           CASE
             WHEN e.event_type = 'Error'                                          THEN 'FAILED_ACTION'
             WHEN e.page_title = 'Mis Movimientos' OR e.action = 'view_transactions' THEN 'REVIEWING_TRANSACTIONS'
             WHEN e.page_title = 'Tarjeta de Crédito'                             THEN 'VIEWING_CREDIT_CARD'
             WHEN e.page_title = 'Ayuda' OR e.action = 'view_help'                THEN 'SEEKING_HELP'
           END AS signal,
           e.page_title,
           e.ip_country,
           e.ip_city,
           e.event_id
    FROM digital_events AS e
    WHERE e.customer_id = %(customer_id)s
      AND e.process_date >= (%(as_of)s::date - 1)
      AND e.event_date >  %(as_of)s - INTERVAL '24 hours'
      AND e.event_date <= %(as_of)s
) AS signals
WHERE signals.signal IS NOT NULL
ORDER BY signals.event_date DESC NULLS LAST, signals.event_id
LIMIT %(limit)s
```
- The rules are checked in order and the first match wins, so an error on any page is `FAILED_ACTION`.
- Every other page (`Inicio`, `Iniciar Sesión`, `Cerrar Sesión`, `Préstamos`, `Cuenta de Ahorro`, `Pagar Servicios`, `Transferir`, `Mis Cuentas`, `Productos`) produces no signal and is filtered out **in SQL**, so the cap counts real signals.
- Matching on `action` as well keeps the signal when `page_title` is null.
- `event_id` is selected only as a stable tie-break. The use case doesn't map it.

### 5.5 `session_open_cases.sql`
```sql
SELECT deduplicated.complaint_id, deduplicated.case_type, deduplicated.category,
       deduplicated.subcategory, deduplicated.status, deduplicated.priority,
       deduplicated.sla_breached, deduplicated.claimed_amount, deduplicated.currency,
       (%(as_of)s::date - deduplicated.creation_date::date) AS days_open
FROM (
    SELECT DISTINCT ON (k.complaint_id) k.*
    FROM complaints AS k
    WHERE k.customer_id = %(customer_id)s
      AND k.creation_date <= %(as_of)s
      AND (k.closing_date IS NULL OR k.closing_date > %(as_of)s)
    ORDER BY k.complaint_id, k.process_date DESC NULLS LAST
) AS deduplicated
ORDER BY deduplicated.sla_breached DESC NULLS LAST,
         deduplicated.creation_date DESC NULLS LAST,
         deduplicated.complaint_id
LIMIT %(limit)s
```
- **"Open at `as_of`":** created on or before `as_of`, and not closed by then. This replaces §7.1's `status NOT IN ('Closed','Resolved')`, because a case that's closed today may still have been open on a past demo date. `status` is returned as it's stored now, so on a past `AS_OF` it can read `Closed`. The model is told nothing extra about this; it's a demo-only effect.
- `date - date` is an integer in PostgreSQL, so `days_open` maps to an `int`.

---

## 6. Errors

### 6.1 Port errors
Copied as they are: `DataAccessError`, `DataSourceConnectionError`, `QueryExecutionError`, `QueryLimitExceededError`, `QueryNotFoundError`.

### 6.2 Domain errors (`domain/errors.py`)
`DomainError`, `InvalidInputError` and `_FixedMessageError` are copied. This tool's fixed-message errors:

| Cause (customer section only) | Domain error | Message |
|---|---|---|
| `DataSourceConnectionError` | `DataSourceUnavailableError` | "Customer data is temporarily unavailable. Greet the customer, ask how you can help, and offer to retry in a moment or hand off to a human agent." |
| any other `DataAccessError` | `SessionContextLookupError` | "The customer's context can't be retrieved right now due to an internal error. Don't retry; ask the customer how you can help and offer a hand-off to a human agent if needed." |
| no row | `CustomerNotFoundError` | "No customer record matches this customer_id. Don't guess or retry; offer a hand-off to a human agent." |
| mapping failure | `SessionContextDataIntegrityError` | "Customer data came back in an unexpected format. Don't retry; offer a hand-off to a human agent." |

Failures in the other sections never raise; they produce `unavailable` (§4.4).

### 6.3 Handler (`delivery/handler.py`)
Copied from `list_credit_cards`, then changed:
- `TOOL_NAME = "get_session_context"`.
- `CLOCK = build_clock(os.environ)` and the `USE_CASE is None or CLOCK is None` guard (§2.3).
- `present_session_context(USE_CASE.execute(customer_id, as_of=CLOCK.now()))`.
- The log line: `"%s returned context (unavailable=%s, truncated=%s)"`, with the two lists. It never logs the customer's data.
- The unexpected-error text becomes "Unexpected internal error loading the customer's context. Offer a hand-off to a human agent."

Everything else stays the same: the wrong-tool-name guard, `DomainError` → `{"error": message}`, any other exception → the generic message, and the `R1` and `R5` TODO tags.

---

## 7. Connection, settings and wiring
Copied from `list_credit_cards` with no behaviour change: the connectors, `DsqlRepository`, `FileQueryProvider`, and `settings.py` (now with `ClockSettings`), with the env vars `DB_ENGINE`, `MAX_ROWS`, `DSQL_CLUSTER_ENDPOINT`, `DSQL_DB_USER`, `AWS_REGION`, plus `AS_OF`.

In `dependencies_builder.py`, the use-case block becomes `build_get_session_context_use_case(env)`, and the clock block is the one from §2.2. Cold start and warm reuse work exactly as in the other tools.

---

## 8. Copy list (risk S4: copies drift)

Each row is copied from `gateway/tools/list_credit_cards/list_credit_cards_lambda/` **after Task 1**, so the copy already has `ClockSettings` and `build_clock`. Every `list_credit_cards_lambda` import becomes `get_session_context_lambda`.

| Copied file | Changed after copy |
|---|---|
| `requirements.txt` (from the tool folder) | Header names this tool |
| `__init__.py` files | Docstrings name this tool |
| `application/ports/{database_repository,query_provider,errors}.py` | Imports only |
| `infrastructure/queries/file_query_provider.py` | Imports only |
| `infrastructure/repositories/dsql_repository.py` | Imports only |
| `utils/connectors/{base,dsql}.py` | Imports only |
| `delivery/settings.py` | Imports only |
| `delivery/dependencies/dependencies_builder.py` | Use-case block and docstrings |
| `delivery/handler.py` | §6.3 |
| `domain/errors.py` | Fixed-message errors replaced (§6.2) |
| `queries/postgresql/list_credit_cards.sql` → `session_credit_cards.sql` | Header comment |

These are new: `session_context.py` (entities), `get_session_context.py` (use case), `session_context.py` (presenter), the other four SQL files and `tool_spec.json`.

---

## 9. Product design doc fixes (`docs/LEDGERLENS_PRODUCT_DESIGN.md`, CRLF)

- **§7 conventions, `:as_of` bullet:** "`:as_of` comes from the optional `AS_OF` env var of each tool Lambda; unset means the real UTC time (production). Demos set it to a timestamp inside the dataset."
- **§7.1:**
  - Replace the output shape with §4.5's.
  - Replace Q1 with the profile/cards split.
  - In Q2: `declined` becomes `= 'Declined'` and the transactions are credit-card only.
  - Replace Q3 with §5.4's mapping.
  - Change Q4 to "open at `as_of`".
  - Add a line linking this spec.
- **§17:**
  - Q1: mark `transaction_status`, `page_title`, `event_type`, `action` and `event_category` as answered, with their values.
  - Q7: answered by `AS_OF`.

---

## 10. Tests (`tests/unit/`, pytest, TDD, no database or AWS)

### 10.1 Task 1 (in each existing tool's test folder)
| File | Covers |
|---|---|
| `test_settings.py` (both tools) | Every row of the §2.1 table; `now()` returns `as_of` when set; `now()` is aware UTC and close to the real time when unset. |
| `test_delivery_wiring.py` (both tools) | `build_clock` returns `ClockSettings`, or `None` on a bad `AS_OF`. |
| `test_list_card_transactions_handler.py` | With a fixed clock, the default `date_to` is `AS_OF`'s date; `CLOCK is None` → unavailable message. |
| `test_list_credit_cards_handler.py` | `CLOCK is None` → unavailable message. |

### 10.2 The new tool (`tests/unit/get_session_context/`)
The folder is a package with an empty `__init__.py`. `conftest.py` puts `gateway/tools/get_session_context` on `sys.path`. `fakes.py` is copied and adapted: it has a fake repository that answers by query name and can raise per query, plus a row builder per section.

| File | Covers |
|---|---|
| `test_get_session_context_use_case.py` | `customer_id` cleaning (as in `list_credit_cards`); a naive `as_of` → `ValueError`; each query gets exactly the params in §4.4 and the same naive UTC `as_of` (an aware `-05:00` input is converted); each customer-section failure → its domain error, and no other query runs; no customer row → `CustomerNotFoundError`; each other section's port error or bad row → `None` + `unavailable`, while the other sections are still returned; all four failing → all four in `unavailable`, in enum order; truncation per section (26 → 25, open cases 6 → 5) in `truncated`; empty sections → empty tuples; flags (each boolean, `None` → not flagged, non-bool → section unavailable, enum order); `max_rows < 1` rejected; `max_rows = 3` caps open cases at 3. |
| `test_session_context_presenter.py` | `as_of` with `Z`; ISO timestamps and dates; 2-decimal half-up amounts; ints and bools kept; `None` → `null`; empty tuple → `[]`; unavailable section → `null`; `truncated`/`unavailable` as lists of names; flags as strings. |
| `test_get_session_context_handler.py` | Success format; the bare `customer_id` and `CLOCK.now()` reach the use case; non-object event / missing id → the `InvalidInputError` message; domain error → `{"error": msg}`; unexpected exception → generic message; wrong tool name; `USE_CASE` or `CLOCK` `None` → unavailable message. |
| `test_query_contracts.py` | For each of the 5 SQL files: every placeholder matches the use case's params and vice versa, and every column the use case reads is selected. No `%` other than placeholders. Exact UTF-8 literals: `'Tarjeta Crédito'` (cards, transactions), `'Declined'`, `'Approved'`, `'Error'`, `'Mis Movimientos'`, `'view_transactions'`, `'Tarjeta de Crédito'`, `'Ayuda'`, `'view_help'`, and the four signal names. `tool_spec.json` is valid, named `get_session_context`, requires only `customer_id`, and its description names the four flags, the four signals, `unavailable` and `truncated`. |
| `test_delivery_wiring.py` | The builder blocks; `build_clock`; the use case wired end to end over a fake connector; `MAX_ROWS` honoured; bad configuration → `None`. |
| `test_errors.py`, `test_settings.py`, `test_file_query_provider.py`, `test_dsql_repository.py`, `test_psycopg_connector.py`, `test_dsql_connector.py` | Copied with imports changed. |

**The whole suite must pass in one session:** `.venv/Scripts/python -m pytest tests/unit -q`.

---

## 11. Risks

| # | Risk | Handling |
|---|---|---|
| R1, R3, R5–R13 | Same as the other tools (no CDK; SQL untested on DSQL; trusted `customer_id`; DSQL connection and packaging notes) | Copied TODO tags. |
| R3 | `percentile_cont ... WITHIN GROUP`, `DISTINCT ON` in a CTE, and `'Infinity'` for numeric haven't been run on DSQL. | TODO tag in `session_recent_transactions.sql`. If DSQL rejects one of them, the transactions section comes back `unavailable` and the rest of the snapshot still works. Check on the first deploy. |
| R8 | Duplicate rows in `customers`, `products`, `transactions`, `complaints` | `DISTINCT ON` in every query. `digital_events` isn't de-duplicated; a duplicate event only repeats a signal. |
| C1 | **Data values.** | **Resolved 2026-10-01:** the user confirmed `transaction_status` (`Approved`, `Declined`, `Pending`, `Reversed`), `page_title` (12 values), `event_type` (7), `action` (10) and `event_category` (4). The contract tests pin the literals that are used. |
| C2 | **Latency:** five sequential queries at session start | Each one reads one customer's rows through the §8.2 indexes. Measure on the first deploy; a pool with parallel queries is a later change behind the same use case. |
| C3 | **A past `AS_OF` shows current statuses** (product, case) | Accepted for demos (§5.5). |
| C4 | **The copies drift** (S4) | The copy list in §8. |
