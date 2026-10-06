# `list_credit_cards` Lambda: Design

**Date:** 2026-10-01
**Status:** Approved 2026-10-01.
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7.3
**Layout rules:** [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md). One folder per tool, wrapping every layer. Code is copied between tools, never shared.
**Copied from:** `gateway/tools/list_card_transactions/` (see §6).

---

## 1. Goal

Build the second Gateway tool Lambda, `list_credit_cards`. It lists a customer's credit cards so the agent can answer "which cards do I have?" and confirm which card the customer means before it calls `list_card_transactions` or `block_credit_card`.

The tool is a self-contained folder on Aurora DSQL with the same hexagonal layers as `list_card_transactions`. It shares no code with that tool. Everything it needs is copied into its own folder and then adapted.

### Success criteria
- `list_credit_cards` returns the customer's credit cards, in every status, as JSON the agent can read. The output follows the §7 conventions: at most 25 rows, amounts as 2-decimal strings with the currency, and card numbers only as `last4`.
- Every failure reaches the agent as one fixed, card-worded message that never shows internals.
- Unit tests cover every layer with no database or AWS. Both tools' tests run together in one pytest session.
- `ruff format --check` and `ruff check` are clean.
- Nothing imports across the two tool folders.

### Decisions already made with the user
| Topic | Decision |
|---|---|
| Card types | **Credit cards only**: `product_type = 'Tarjeta Crédito'` (exact match, a value from the dataset). |
| Statuses | **Every status** (`Active`, `Blocked`, `Closed`, `Suspended`). There's no status input. |
| Handler | Copied from `list_card_transactions` and adapted. |
| Row mapping | The mapping helpers stay **inside the use case module**. There's no shared `row_mapping.py`. |
| `customer_id` | Passed **bare**, exactly as it comes in the event. There's no input value object. The use case cleans it before using it (§3.1). |
| No cards | Not an error. `cards` comes back `null` and the agent tells the customer they have no credit cards. |
| Errors, entities, builder | Each defined in this tool's own folder, with card wording. |
| Package name | `list_credit_cards_lambda`, in the folder `gateway/tools/list_credit_cards/`. |

### Out of scope
- Debit cards (`Tarjeta Débito`) and every other product type.
- `get_session_context`, `block_credit_card`, and every other tool. The only change outside this tool is the product design fix in §7.
- CDK: no Lambda, Gateway target or grants yet (R1).
- Pulling shared code out of the two tools.

---

## 2. Layout

```
gateway/tools/list_credit_cards/                 ← Lambda asset root for this tool only
├── tool_spec.json
├── requirements.txt                             (copy)
└── list_credit_cards_lambda/
    ├── __init__.py
    ├── domain/
    │   ├── entities/credit_card.py              CreditCard, CreditCardsResult
    │   └── errors.py                            card-worded domain errors
    ├── application/
    │   ├── ports/{database_repository,query_provider,errors}.py   (copy)
    │   └── use_cases/list_credit_cards.py       ListCreditCardsUseCase + mapping helpers
    ├── infrastructure/
    │   ├── queries/file_query_provider.py       (copy)
    │   └── repositories/dsql_repository.py      (copy)
    ├── utils/connectors/{base,dsql}.py          (copy)
    ├── delivery/
    │   ├── handler.py
    │   ├── settings.py                          (copy)
    │   ├── dependencies/dependencies_builder.py build_list_credit_cards_use_case
    │   └── presenters/credit_cards.py           present_credit_cards
    └── queries/postgresql/list_credit_cards.sql

tests/unit/list_credit_cards/                    ← package (has __init__.py)
├── __init__.py, conftest.py, fakes.py
└── test_*.py
```

- **Handler string:** `list_credit_cards_lambda/delivery/handler.handler`.
- **Tool name** (the Gateway sends it as `<target>___list_credit_cards`): `list_credit_cards`.
- **Gateway target, for the CDK spec later:** `list-credit-cards-target`.

---

## 3. Contracts

### 3.1 Input: the bare `customer_id`

The handler reads `customer_id` straight from the event and passes it to the use case as it came: `event.get("customer_id")` when the event is a JSON object, `None` otherwise. There's no value object; the tool has a single input.

The use case cleans it before it touches the database, in a private helper `_clean_customer_id(raw: object) -> str` in the use case module:
- A value that isn't a string (missing, `None`, a number, a list) raises `InvalidInputError("customer_id", "is required and must be a non-empty string")`.
- Leading and trailing whitespace is stripped, then the id is uppercased. Customer ids look like `CLI-ITIECUE8PRH9` (uppercase letters and digits), so ` cli-itiecue8prh9 ` becomes `CLI-ITIECUE8PRH9` instead of finding no cards.
- A string that is empty after stripping raises the same error.
- There is no format check. An id that is malformed or belongs to no customer just finds no cards (`"cards": null`). Whether the caller may see this customer at all is decided by the Cedar policy at the Gateway, not here (R5).

Unknown keys in the event are ignored, as in `list_card_transactions`.

### 3.2 Entities (`domain/entities/credit_card.py`)

```python
@dataclass(frozen=True)
class CreditCard:
    card_last4: str | None
    product_status: str | None
    currency: str | None
    current_balance: Decimal | None
    credit_limit: Decimal | None
    available_credit: Decimal | None
    expiration_date: date | None
    days_past_due: int | None

@dataclass(frozen=True)
class CreditCardsResult:
    cards: tuple[CreditCard, ...]
    truncated: bool
```

**Every field is nullable.** The ERD notes about 5% nulls in nullable fields. A card with a null column is listed with that field as `null`; it never turns the whole call into an error.

`CreditCardsResult.cards` is an empty tuple when the customer has no credit cards. The presenter turns that into `null` (§3.4).

`product_status` is a plain string, not an enum. The tool doesn't filter on it, and the data may hold values outside the four known ones.

`product_id` isn't returned. Other tools address cards by `card_last4`, and the §7 conventions keep internal identifiers out of the model's view.

### 3.3 Use case (`application/use_cases/list_credit_cards.py`)

`ListCreditCardsUseCase(database_repository, query_provider, max_rows=25)` has the same shape as `ListCardTransactionsUseCase`:
- `QUERY_NAME = "list_credit_cards"`.
- `execute(customer_id: object) -> CreditCardsResult` first cleans the id with `_clean_customer_id` (§3.1). Then it runs the query with `{"customer_id": <cleaned id>, "limit": max_rows + 1}`. It maps the first `max_rows` rows and sets `truncated` when an extra row came back. No rows gives an empty result, not an error.
- Port errors become domain errors (§4).
- Mapping errors (`KeyError`, `TypeError`, `ValueError`) become `CardDataIntegrityError`.
- The mapping helpers sit at the bottom of the same module:
  - `_clean_customer_id`
  - `_to_card`
  - `_optional_text`
  - `_optional_amount`: a finite number becomes a `Decimal`. A bool is rejected, as in the first tool.
  - `_optional_date`: a `datetime` becomes its `.date()`. A `date` is kept as it is. Anything else raises `TypeError`.
  - `_optional_int`: a bool is rejected.
  - `None` passes through every helper unchanged.

### 3.4 Output to the agent (`delivery/presenters/credit_cards.py`)

`present_credit_cards(result)` returns this shape:
```json
{
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
  "count": 1,
  "truncated": false
}
```
- Amounts are rounded half-up to strings with 2 decimals.
- Dates are ISO strings (`YYYY-MM-DD`).
- `None` becomes JSON `null`.
- `days_past_due` stays an integer.
- **No cards:** `{"cards": null, "count": 0, "truncated": false}`. The agent reads `null` as "this customer has no credit cards" and says so.

### 3.5 SQL (`queries/postgresql/list_credit_cards.sql`)

```sql
SELECT deduplicated.*
FROM (
    SELECT DISTINCT ON (p.product_id)
           p.product_id,
           RIGHT(p.product_number, 4)          AS card_last4,
           p.product_status,
           p.currency,
           p.current_balance,
           p.credit_limit,
           p.credit_limit - p.current_balance  AS available_credit,
           p.expiration_date,
           p.days_past_due
    FROM products AS p
    WHERE p.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
    ORDER BY p.product_id, p.last_updated DESC NULLS LAST
) AS deduplicated
ORDER BY (deduplicated.product_status = 'Active') DESC NULLS LAST,
         deduplicated.expiration_date DESC NULLS LAST,
         deduplicated.product_id
LIMIT %(limit)s
```
- **Duplicates:** about 2% of rows are duplicates (R8). `DISTINCT ON (product_id)` keeps the most recently updated copy.
- **Order:** active cards come first, then the cards that expire latest. `product_id` is a stable tie-break, so the result is deterministic. The use case doesn't map `product_id`; it's selected only for ordering.
- **`available_credit`** is `NULL` when either operand is `NULL`. It can be negative when the customer is over the limit, and it's returned as it is.
- **The literal `'Tarjeta Crédito'`** is in the SQL file, not a bind. The file is read as UTF-8 and the connection uses `client_encoding=utf8`, so the accent arrives intact. A contract test pins the exact bytes.
- **Literal `%` characters** (there are none) would have to be written `%%`, because of psycopg's named placeholders.
- The header comment follows the first tool's: parameters, the reasons above, and the `R3` and `R8` TODO tags.

### 3.6 `tool_spec.json`

```json
[
  {
    "name": "list_credit_cards",
    "description": "Lists the customer's credit cards in every status (active, blocked, closed, suspended) with last 4 digits, status, currency, balance, credit limit, available credit, expiry date and days past due. Use when the customer asks about their cards, or to confirm which card they mean before searching transactions or blocking a card. Returns at most 25 cards, active first, as JSON with 'cards', 'count' and 'truncated'. Amounts are strings with 2 decimals in the card's currency. 'cards' is null when the customer has no credit cards.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's id from get_session_context."
        }
      },
      "required": ["customer_id"]
    }
  }
]
```

---

## 4. Errors

### 4.1 Port errors

Copied as they are: `DataAccessError`, `DataSourceConnectionError`, `QueryExecutionError`, `QueryLimitExceededError`, `QueryNotFoundError`.

### 4.2 Domain errors (`domain/errors.py`)

`DomainError`, `InvalidInputError` and `_FixedMessageError` are copied. The fixed-message errors are this tool's own:

| Port error | Domain error | Message |
|---|---|---|
| `DataSourceConnectionError` | `DataSourceUnavailableError` | "Card data is temporarily unavailable. Tell the customer and offer to retry in a moment or hand off to a human agent." |
| `QueryLimitExceededError` and any other `DataAccessError` | `CardLookupError` | "The customer's cards can't be retrieved right now due to an internal error. Don't retry; offer a hand-off to a human agent." |
| (mapping failure) | `CardDataIntegrityError` | "Card data came back in an unexpected format. Don't retry; offer a hand-off to a human agent." |

There is no `SearchTooBroadError`. The query has no filter the agent could narrow, so "narrow the search" would be advice it can't follow. A limit error on a single customer's cards is an internal problem, so it gets the same message as any other failure.

### 4.3 Handler (`delivery/handler.py`)

Copied from the first tool, then changed in four places:
- `TOOL_NAME = "list_credit_cards"`.
- It passes the bare `customer_id` to `USE_CASE.execute` (§3.1): `event.get("customer_id")` when the event is a JSON object, `None` otherwise. It needs no `today`.
- It calls `present_credit_cards`.
- It logs `"%s returned %d cards (truncated=%s)"`.

The unexpected-error text becomes "Unexpected internal error listing credit cards. Offer a hand-off to a human agent."

Everything else stays the same as the first tool:
- the wrong-tool-name guard
- `USE_CASE is None` → `DataSourceUnavailableError`
- `DomainError` → `{"error": message}`
- any other exception → the generic message
- the `R1` and `R5` TODO tags

---

## 5. Connection, settings and wiring

These are copied from `list_card_transactions` with no behaviour change:
- the connectors, `DsqlRepository` and `FileQueryProvider`
- `settings.py`, with the same env vars: `DB_ENGINE`, `MAX_ROWS`, `DSQL_CLUSTER_ENDPOINT`, `DSQL_DB_USER`, `DSQL_REGION`

In `dependencies_builder.py`, the only change is the use-case block: `build_list_credit_cards_use_case(env)` replaces `build_list_card_transactions_use_case`. Its docstrings name this tool.

Cold start and warm reuse work exactly as in the first tool:
- The graph is built once when the module loads.
- The connection is opened eagerly. If that fails, the use case still works and reconnects on the first call.
- Bad configuration gives `None`, so the handler answers with the unavailable message.

---

## 6. Copy list (risk S4: copies drift)

Each row is copied from `gateway/tools/list_card_transactions/list_card_transactions_lambda/`. After the copy, every `list_card_transactions_lambda` import becomes `list_credit_cards_lambda`.

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
| `delivery/handler.py` | §4.3 |
| `domain/errors.py` | Fixed-message errors replaced (§4.2) |

These are new: `credit_card.py`, `list_credit_cards.py` (use case and SQL), `credit_cards.py` (presenter) and `tool_spec.json`.

`list_card_transactions` has a `domain/value_objects/` folder; this tool has none, because it takes no filters.

---

## 7. Product design fix

`docs/LEDGERLENS_PRODUCT_DESIGN.md` filters cards with `product_type ILIKE '%card%'`. The dataset's values are in Spanish, so that pattern matches nothing. Fixes:
- **§7.1 Q1** (`get_session_context` cards): `AND p.product_type = 'Tarjeta Crédito'`. Its output has `available_credit`, so it's about credit cards.
- **§7.7** (`block_credit_card`): `AND product_type = 'Tarjeta Crédito'`.
- **§7.3:** add a line under the description: "Credit cards only (`product_type = 'Tarjeta Crédito'`), in every status, active first. Spec: [2026-10-01-list-credit-cards-lambda-design.md](superpowers/specs/2026-10-01-list-credit-cards-lambda-design.md)."

---

## 8. Tests (`tests/unit/list_credit_cards/`, pytest, TDD, no database or AWS)

The folder is a package with an empty `__init__.py`. `conftest.py` puts `gateway/tools/list_credit_cards` on `sys.path`. `fakes.py` is copied from the first tool's tests and adapted: `make_row` builds a card row. There's no filters builder; tests pass the `customer_id` directly.

| File | Covers |
|---|---|
| `test_list_credit_cards_use_case.py` | `customer_id` cleaning: missing, `None`, non-string and blank ids raise `InvalidInputError` before the database is called; surrounding whitespace is stripped and the id is uppercased (` cli-itiecue8prh9 ` → `CLI-ITIECUE8PRH9`); nothing else changes. The SQL name and the exact params (`customer_id`, `limit` = max_rows + 1). Row mapping, including every-field-null and `datetime` → `date`. Truncation (26 → 25 plus `truncated`). An empty result. Each port error → its domain error. Bad rows (wrong types, bool amount, non-finite amount) → `CardDataIntegrityError`. `max_rows < 1` rejected. |
| `test_credit_cards_presenter.py` | 2-decimal half-up strings, ISO dates, nulls, `count`, `truncated`; no cards → `"cards": null`, `count` 0 |
| `test_list_credit_cards_handler.py` | Success format; the bare `customer_id` reaches the use case unchanged; a non-object event and a missing id → the `InvalidInputError` message; no cards → `"cards": null`; domain error → `{"error": msg}`; unexpected exception → generic message; wrong tool name; missing configuration → unavailable message |
| `test_query_contracts.py` | Every SQL placeholder matches `_params` keys and vice versa. The SQL holds the exact literal `'Tarjeta Crédito'`, read as UTF-8. Every selected column the use case reads is in the SQL. `tool_spec.json` is valid, named `list_credit_cards`, requires only `customer_id`, and its description says 25 and that `cards` can be null. |
| `test_delivery_wiring.py` | The builder blocks; the use case wired end to end over a fake connector; `MAX_ROWS` honoured; bad configuration → `None` |
| `test_errors.py`, `test_settings.py`, `test_file_query_provider.py`, `test_dsql_repository.py`, `test_psycopg_connector.py`, `test_dsql_connector.py` | Copied with imports changed, so the copied code is covered in this tool too |

**The whole suite must pass in one session:** `pytest tests/unit -q`. Today that's 261 tests plus the new ones. That run proves the two test packages and the two production packages don't collide.

---

## 9. Risks

| # | Risk | Handling |
|---|---|---|
| R1, R3, R5–R13 | Same as `list_card_transactions` (no CDK; SQL untested on DSQL; trusted `customer_id`; DSQL connection and packaging notes) | Copied TODO tags. They're fixed in both tools when the follow-up specs land. |
| R8 | Duplicate `products` rows | `DISTINCT ON (product_id)` keeping the latest `last_updated` |
| C1 | **`product_type` spelling.** If the loaded data spells the value differently (accents or encoding), the tool silently returns `"cards": null`, and the agent wrongly tells the customer they have no credit cards. | **Resolved 2026-10-01:** the data owner confirmed the stored values are exactly `'Tarjeta Crédito'` (`product_type`) and `'Active'` (`product_status`). The contract test pins the literal's spelling and encoding. |
| C2 | **The two copies drift** (risk S4) | The copy list in §6 |
