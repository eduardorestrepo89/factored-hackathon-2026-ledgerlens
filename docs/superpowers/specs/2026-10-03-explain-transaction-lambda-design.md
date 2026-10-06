# `explain_transaction` Lambda: Design

**Date:** 2026-10-03
**Status:** Draft, awaiting the user's review.
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7.5
**Layout rules:** [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md). One folder per tool, wrapping every layer. Code is copied between tools, never shared.
**Copied from:** `gateway/tools/get_session_context/` (see §9). This copy brings `ClockSettings`, `build_clock`, and the partial-failure `unavailable` pattern.
**Siblings:** [transaction_fraud_detection](2026-10-03-transaction-fraud-detection-lambda-design.md) (built first) and [classify_call_type](2026-10-03-classify-call-type-lambda-design.md). Build order: fraud, then this tool, then classify.

---

## 1. Goal

When a customer asks "what is this charge?", the agent calls this tool with the charge. It returns the facts needed to explain it:

- **The charge itself:** merchant, amount, channel, place, status.
- **FX:** for a charge in another currency, what it cost in the card's currency.
- **The decline:** for a declined charge, what the response code means, and whether it contradicts the card's state.
- **Habit:** how the charge compares with the card's last 90 days.
- **App activity:** whether the customer's app or web session was in another country around the time of an in-person charge.

The tool explains; it doesn't judge fraud. Fraud is `transaction_fraud_detection`'s job, so this tool has no fraud fields.

### Success criteria
- The core section (the charge) is required. FX and decline are computed from the core row, with no extra query. Habit and app activity are separate queries. When one fails, it comes back `null` and is listed in `unavailable`, and the rest is still returned.
- Credit cards only, with the ownership check on `customer_id`. A missing charge, or one that belongs to someone else, returns "not found".
- No query reads `fraud_score` or `is_fraud`. A contract test enforces this.
- Amounts are 2-decimal strings. Card numbers appear only as `last4`.
- **Acceptance on the deployed stack** (`AS_OF = 2026-06-17T23:59:59`):
  - P07 `TRX-23BIJAU4GL46ATPW9STY`: `fx: null` (USD on a USD card), `decline: null`, `habit` filled, `app_activity.found` false or true.
  - P05 `TRX-YLR3CXW0CFHFUNT2IUWZ` (Declined, code 14): `decline.response_code "14"`, meaning "invalid card number", `contradicts_card_state: false`.
  - P05 `TRX-MQKFELIPWT098DXTN2WN` (Brazil, POS, USD on a USD card): `fx: null`. `habit.country_seen_before` is false unless Brazil appears in the card's prior 90 days.
  - P09 `TRX-RX1ENVJQ5J26GXX7T8F7` (Declined, code 54, card valid until 2029): `contradicts_card_state: true`.
  - P03 `TRX-LJGEBUAOX0G4CL4RQSIU`: `transaction_status "Reversed"`, `decline: null`.
- Unit tests cover every layer with no database or AWS. `ruff` is clean. Nothing imports across tool folders.

### Decisions made with the user
| Topic | Decision |
|---|---|
| Scope | **§7.5 only.** The tool explains the charge and adds no fraud verdict. |
| App activity | **Kept.** The user decided this after being told it's usually empty: only 897 customers have app activity in any 24 hours (D36), and event streams aren't linked to card activity. The output says `found: false` plainly when there's nothing. |
| FX | `daily_exchange_rates.sell_rate` on the charge's date. Only used when the charge currency differs from the card's. |
| Decline | Shown only for `Declined` charges. Pending and Reversed charges carry response codes too (X2 profiling), but they aren't declines. |

### Out of scope
- Fraud verdicts, scores, and "is this suspicious" wording.
- Explaining several charges in one call. The agent calls the tool once per charge.
- The Gateway target and the agent's prompt changes.

---

## 2. Layout

```
gateway/tools/explain_transaction/                          ← Lambda asset root for this tool only
├── tool_spec.json
├── requirements.txt                                        (copy)
└── explain_transaction_lambda/
    ├── __init__.py
    ├── domain/
    │   ├── value_objects/decline_codes.py                  DECLINE_MEANINGS, IN_PERSON_CHANNELS
    │   ├── value_objects/text_folding.py                   fold_text()
    │   ├── entities/transaction_explanation.py             ExplainedTransaction, FxConversion, DeclineInfo,
    │   │                                                   SpendingHabit, AppActivity, TransactionExplanation
    │   └── errors.py
    ├── application/
    │   ├── ports/{database_repository,query_provider,errors}.py   (copy)
    │   └── use_cases/explain_transaction.py                ExplainTransactionUseCase
    ├── infrastructure/
    │   ├── queries/file_query_provider.py                  (copy)
    │   └── repositories/dsql_repository.py                 (copy)
    ├── utils/connectors/{base,dsql}.py                     (copy)
    ├── delivery/
    │   ├── handler.py
    │   ├── settings.py                                     (copy, with ClockSettings)
    │   ├── dependencies/dependencies_builder.py            build_explain_transaction_use_case, build_clock
    │   └── presenters/transaction_explanation.py           present_transaction_explanation
    └── queries/postgresql/
        ├── explain_transaction.sql
        ├── transaction_habit.sql
        └── transaction_app_activity.sql

tests/unit/explain_transaction/                             ← package (has __init__.py)
```

- **Handler string:** `explain_transaction_lambda/delivery/handler.handler`.
- **Tool name:** `explain_transaction`.
- **Lambda:** `ledgerlens-explain-transaction` (§7).

---

## 3. Domain

### 3.1 Decline codes (`domain/value_objects/decline_codes.py`)

```python
DECLINE_MEANINGS: Final[Mapping[str, str]] = {
    "05": "declined by the issuer, no specific reason",
    "14": "invalid card number",
    "51": "insufficient available credit",
    "54": "expired card",
}
EXPIRED_CARD_CODE: Final = "54"
IN_PERSON_CHANNELS: Final = frozenset({"ATM", "POS", "Branch"})
```

- Response codes in the data are `00`, `05`, `14`, `51`, `54` and NULL (X2). Declined rows only carry the last four, or NULL.
- An unknown code shows the code with a `null` meaning. A NULL code shows both as `null`.
- The transaction channels in the data are `App`, `ATM`, `Branch`, `POS` and `Web` (X14). Only ATM, POS and Branch are in person. App and Web charges can come from anywhere, so they never produce a conflict.

### 3.2 Text folding (`domain/value_objects/text_folding.py`)

`fold_text(value: str | None) -> str | None`: NFKD-decomposes the text, drops combining marks, casefolds it and strips spaces. `None` stays `None`. "México" and " mexico " fold to the same value (D21). Python uses this for the app-activity conflict. The SQL in §6.2 uses `translate()` with the mapping from `list_card_transactions.sql`.

### 3.3 Entities (`domain/entities/transaction_explanation.py`)

```python
@dataclass(frozen=True)
class ExplainedTransaction:
    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    merchant_category: str | None
    amount: Decimal | None
    currency: str | None
    channel: str | None
    transaction_city: str | None
    transaction_country: str | None
    transaction_status: str | None

@dataclass(frozen=True)
class FxConversion:
    card_currency: str
    rate_date: date | None
    rate: Decimal | None                       # sell_rate; None when that day has no row
    amount_in_card_currency: Decimal | None    # amount * rate, 2 decimals half-up; None without a rate

@dataclass(frozen=True)
class DeclineInfo:
    response_code: str | None
    meaning: str | None
    contradicts_card_state: bool | None

@dataclass(frozen=True)
class UsualAmountRange:
    low: Decimal
    high: Decimal
    currency: str

@dataclass(frozen=True)
class SpendingHabit:
    history_count: int
    times_at_merchant_90d: int | None          # None when the charge has no merchant
    usual_amount_range: UsualAmountRange | None
    country_seen_before: bool | None           # None when the charge has no country

@dataclass(frozen=True)
class AppActivity:
    found: bool
    event_date: datetime | None = None
    minutes_from_charge: int | None = None     # event minus charge; negative means before
    ip_country: str | None = None
    ip_city: str | None = None
    conflict: bool | None = None

class Section(StrEnum):
    HABIT = "habit"
    APP_ACTIVITY = "app_activity"

@dataclass(frozen=True)
class TransactionExplanation:
    transaction: ExplainedTransaction
    fx: FxConversion | None
    decline: DeclineInfo | None
    habit: SpendingHabit | None
    app_activity: AppActivity | None
    unavailable: tuple[Section, ...]
```

### 3.4 Rules

| Field | Rule |
|---|---|
| `fx` | `None` when the charge currency equals the card currency, or either is NULL. Otherwise it's a `FxConversion`. `rate_date` is the charge's date, and `rate` is the SQL's `fx_sell_rate`, which may be NULL. |
| `decline` | `None` unless `transaction_status == "Declined"`. |
| `decline.meaning` | `DECLINE_MEANINGS.get(code)`. |
| `decline.contradicts_card_state` | Code `54` with a card expiration date on or after the charge date: `True`. That card wasn't expired, so the decline contradicts the card state (D18). Code `54` with an earlier expiration date: `False`. Code `54` with a NULL expiration date or charge date: `None`. Any other code, or NULL: `False`. |
| `habit.usual_amount_range` | `None` when fewer than 3 approved charges in the same currency are in the window. That's a spec choice: one or two charges don't make a range. Otherwise the 10th to 90th percentile of their amounts. |
| `app_activity.conflict` | `None` when the charge's country, the channel or `ip_country` is NULL. Otherwise `True` when `fold_text(ip_country) != fold_text(transaction_country)` and the channel is in `IN_PERSON_CHANNELS`, else `False`. |
| `app_activity.minutes_from_charge` | `round((event_date - transaction_date).total_seconds() / 60)`. |

---

## 4. Use case (`application/use_cases/explain_transaction.py`)

```python
class ExplainTransactionUseCase:
    def __init__(self, database_repository, query_provider): ...
    def execute(self, customer_id: object, transaction_id: object, as_of: datetime) -> TransactionExplanation: ...
```

**Order inside `execute`:**
1. Clean the inputs:
   - `customer_id`: copied `_clean_customer_id`.
   - `transaction_id`: a non-empty string, stripped and uppercased, else `InvalidInputError("transaction_id", "is required and must be a non-empty string")`.
   - `as_of` must be aware (`ValueError` otherwise). It's converted to naive UTC.
2. **Core** (`explain_transaction`). No row → `TransactionNotFoundError`. `DataSourceConnectionError` → `DataSourceUnavailableError`. Any other `DataAccessError` → `ExplainLookupError`. A mapping error → `ExplainDataIntegrityError`.
3. Build `fx` and `decline` from the core row (§3.4).
4. **Habit** (`transaction_habit`) and then **app activity** (`transaction_app_activity`), each in its own `try`, as in `get_session_context`. Any `DataAccessError` or mapping error makes the section `None`, adds it to `unavailable`, and logs a warning. When the charge's `transaction_date` is NULL, neither query runs, and both sections are listed in `unavailable`.
5. App activity: when no row comes back, the section is `AppActivity(found=False)`, not `None`. `None` means the query failed.

**Params each query gets:**

| Query | Params |
|---|---|
| `explain_transaction` | `customer_id`, `transaction_id`, `as_of` |
| `transaction_habit` | `customer_id`, `product_id`, `transaction_id`, `charge_date`, `merchant_name`, `currency`, `transaction_country` |
| `transaction_app_activity` | `customer_id`, `charge_date`, `as_of` |

- `product_id` and `card_expiration_date` come from the core row. They're used internally and never presented.
- `charge_date` is the core row's `transaction_date`.

---

## 5. Output to the agent (`delivery/presenters/transaction_explanation.py`)

```json
{
  "transaction": {
    "transaction_id": "TRX-23BIJAU4GL46ATPW9STY",
    "transaction_date": "2026-05-31T06:09:15",
    "card_last4": "4497",
    "merchant_name": "Estación de Servicio",
    "merchant_category": "Transport",
    "amount": "288.69",
    "currency": "USD",
    "channel": "Web",
    "transaction_city": "Ciudad de México",
    "transaction_country": "México",
    "transaction_status": "Approved"
  },
  "fx": null,
  "decline": null,
  "habit": {
    "history_count": 1,
    "times_at_merchant_90d": 0,
    "usual_amount_range": null,
    "country_seen_before": true
  },
  "app_activity": { "found": false },
  "unavailable": []
}
```

The habit values are what P07's data gives: card 4497 had one approved charge in the 90 days before 2026-05-31 (TRX-1X85VYUX188U9MRNSAGG, 2026-03-20, Mexico). With fewer than 3 charges, the range is `null`.

- `fx`, when present: `{"card_currency", "rate_date", "rate", "amount_in_card_currency"}`. `rate` is a string with all its stored decimals. The amount has 2 decimals.
- `decline`, when present: `{"response_code", "meaning", "contradicts_card_state"}`.
- `app_activity` with `found: true`: `{"found", "event_date", "minutes_from_charge", "ip_country", "ip_city", "conflict"}`. With `found: false` it's only `{"found": false}`.
- A failed section is `null` and is listed in `unavailable`.
- No key in the output contains `fraud` or `score`. A presenter test walks the whole JSON.

### 5.1 `tool_spec.json`

```json
[
  {
    "name": "explain_transaction",
    "description": "Explains one credit-card charge so you can tell the customer what it is: the charge (merchant, amount, channel, place, status); 'fx' when it was in another currency (sell rate on that day and the amount in the card's currency, rate null if the bank has no rate for that day); 'decline' for declined charges (response code, its meaning, and contradicts_card_state = true when the code says expired but the card wasn't); 'habit' over the card's 90 days before the charge (how many approved charges, visits to this merchant, usual amount range, whether the country was seen before); 'app_activity': the customer's app or web session closest to the charge within 2 hours, with conflict = true when it was in another country during an in-person charge. App activity is usually not found; that's normal, not a sign of anything. This tool doesn't judge fraud: use transaction_fraud_detection for that. A null section couldn't be loaded and is named in 'unavailable'. Amounts are strings with 2 decimals.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's ID from SESSION CONTEXT." },
        "transaction_id": { "type": "string", "description": "The charge to explain, e.g. TRX-23BIJAU4GL46ATPW9STY." }
      },
      "required": ["customer_id", "transaction_id"]
    }
  }
]
```

---

## 6. SQL (`queries/postgresql/`)

The conventions are the same as the sibling specs: psycopg named placeholders, no stray `%`, no `SET`, NFC UTF-8 with no BOM, `DISTINCT ON` for R8, and the R3/R8 TODO tags.

### 6.1 `explain_transaction.sql` (core)
```sql
SELECT DISTINCT ON (t.transaction_id)
       t.transaction_id, t.transaction_date,
       t.product_id,
       RIGHT(p.product_number, 4) AS card_last4,
       p.currency                 AS card_currency,
       p.expiration_date          AS card_expiration_date,
       t.merchant_name, t.merchant_category, t.amount, t.currency, t.channel,
       t.transaction_city, t.transaction_country, t.transaction_status, t.response_code,
       fx.sell_rate               AS fx_sell_rate
FROM transactions AS t
JOIN products AS p ON p.product_id = t.product_id
LEFT JOIN daily_exchange_rates AS fx
       ON fx.date = t.transaction_date::date
      AND fx.source_currency = t.currency
      AND fx.target_currency = p.currency
      AND t.currency <> p.currency
WHERE t.transaction_id = %(transaction_id)s
  AND t.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND t.transaction_date <= %(as_of)s
ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST, p.last_updated DESC NULLS LAST
```
- **FX direction:** `source_currency` is the charge currency and `target_currency` is the card currency. A rate of 16.9 for USD→MXN means 1 USD = 16.9 MXN (Q6 profiling).
  - Only that exact pair is used. The inverse pair is never used to derive a rate.
  - The table covers ARS, COP, MXN and USD in every direction, daily from 2023-06-17 to 2026-06-17. Any other currency gets a NULL rate.
- `DISTINCT ON` with `p.last_updated` picks one row when `products` or `daily_exchange_rates` has duplicates.

### 6.2 `transaction_habit.sql`
```sql
WITH hist AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.merchant_name, t.amount, t.currency, t.transaction_country
    FROM transactions AS t
    WHERE t.customer_id = %(customer_id)s
      AND t.product_id = %(product_id)s
      AND t.transaction_status = 'Approved'
      AND t.transaction_id <> %(transaction_id)s
      AND t.process_date >= (%(charge_date)s::date - 91)
      AND t.transaction_date >= %(charge_date)s - INTERVAL '90 days'
      AND t.transaction_date <  %(charge_date)s
    ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
)
SELECT COUNT(*) AS history_count,
       CASE WHEN %(merchant_name)s::text IS NULL THEN NULL
            ELSE COUNT(*) FILTER (WHERE merchant_name = %(merchant_name)s::text) END AS times_at_merchant,
       COUNT(*) FILTER (WHERE currency = %(currency)s::text) AS same_currency_count,
       (percentile_cont(0.1) WITHIN GROUP (ORDER BY amount)
            FILTER (WHERE currency = %(currency)s::text))::numeric AS usual_low,
       (percentile_cont(0.9) WITHIN GROUP (ORDER BY amount)
            FILTER (WHERE currency = %(currency)s::text))::numeric AS usual_high,
       CASE WHEN %(transaction_country)s::text IS NULL THEN NULL
            ELSE COALESCE(bool_or(
                lower(translate(btrim(transaction_country), '<accents>', '<plain>'))
                = lower(translate(btrim(%(transaction_country)s::text), '<accents>', '<plain>'))), FALSE)
       END AS country_seen_before
FROM hist
```
- `<accents>` and `<plain>` stand for the exact mapping strings in `list_card_transactions.sql`, `'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÑÇáàâãäéèêëíìîïóòôõöúùûüñç'` and `'AAAAAEEEEIIIIOOOOOUUUUNCaaaaaeeeeiiiiooooouuuunc'`. The SQL file holds the literal strings, not these placeholders.
- "Same card" means the same `product_id`. Habit history covers Approved charges only. The charge itself is never in its own history.
- The query always returns one row, because it's an aggregate. With no history: `history_count` is 0, the percentiles are NULL, and `country_seen_before` is false.

### 6.3 `transaction_app_activity.sql`
```sql
SELECT e.event_id, e.event_date, e.ip_country, e.ip_city
FROM digital_events AS e
WHERE e.customer_id = %(customer_id)s
  AND e.ip_country IS NOT NULL
  AND e.process_date BETWEEN (%(charge_date)s::date - 1) AND (%(charge_date)s::date + 1)
  AND e.event_date BETWEEN %(charge_date)s - INTERVAL '2 hours' AND %(charge_date)s + INTERVAL '2 hours'
  AND e.event_date <= %(as_of)s
ORDER BY ABS(EXTRACT(EPOCH FROM (e.event_date - %(charge_date)s))), e.event_id
LIMIT 1
```
- Both bounds of the ±2-hour window are inclusive. Of two events the same distance from the charge, the lower `event_id` wins.
- `digital_events` isn't de-duplicated. A duplicate event only repeats the same row.

---

## 7. CDK (`infra-cdk/lib/data-construct.ts`)

This change needs the user's approval. Approving this spec approves it.

- Add `{ tool: "explain_transaction", id: "ExplainTransaction" }` to the `tools` array. This gives the function `ledgerlens-explain-transaction`.
- `data-construct.test.ts`:
  - The `vpcFns` count goes up by one: 6 after the fraud tool.
  - Add a `test.each` row `["explain_transaction", "ledgerlens-explain-transaction"]`.
- Deploy with the same command as the fraud spec, then run the §1 acceptance checks with the client context `target___explain_transaction`.

---

## 8. Errors

### 8.1 Port errors
Copied as they are.

### 8.2 Domain errors (`domain/errors.py`)

| Cause (core section only) | Domain error | Message |
|---|---|---|
| no row | `TransactionNotFoundError` | "No credit-card charge with this transaction_id belongs to this customer. Don't guess; ask the customer to confirm the charge, or call list_card_transactions to find it." |
| `DataSourceConnectionError` | `DataSourceUnavailableError` | "Transaction details are temporarily unavailable. Offer to retry in a moment or hand off to a human agent." |
| any other `DataAccessError` | `ExplainLookupError` | "The charge can't be explained right now due to an internal error. Don't retry; offer a hand-off to a human agent." |
| mapping failure | `ExplainDataIntegrityError` | "The charge's data came back in an unexpected format. Don't retry; offer a hand-off to a human agent." |

Habit and app-activity failures never raise. They produce `unavailable`.

### 8.3 Handler
Copied from `get_session_context`, then changed:
- `TOOL_NAME = "explain_transaction"`.
- It passes `event.get("customer_id")` and `event.get("transaction_id")` (or `None` for a non-object event).
- `present_transaction_explanation(USE_CASE.execute(customer_id, transaction_id, as_of=CLOCK.now()))`.
- It logs `unavailable` only, never customer data.
- The unexpected-error text is "Unexpected internal error explaining the charge. Offer a hand-off to a human agent."

---

## 9. Copy list

The same table as the fraud spec's §9, from `get_session_context_lambda/` to `explain_transaction_lambda/`:

| Copied file | Changed after copy |
|---|---|
| `requirements.txt` (from the tool folder) | Header names this tool |
| `__init__.py` files | Docstrings name this tool |
| `application/ports/{database_repository,query_provider,errors}.py` | Imports only |
| `infrastructure/queries/file_query_provider.py` | Imports only |
| `infrastructure/repositories/dsql_repository.py` | Imports only |
| `utils/connectors/{base,dsql}.py` | Imports only |
| `delivery/settings.py` | Imports only |
| `delivery/dependencies/dependencies_builder.py` | Use-case block and docstrings. There's no `MAX_ROWS` use, since the tool returns one charge. The setting is still parsed, so the settings stay identical to the other tools'. |
| `delivery/handler.py` | §8.3 |
| `domain/errors.py` | Fixed-message errors replaced (§8.2) |

New files: `decline_codes.py`, `text_folding.py`, the entities, the use case, the presenter, the three SQL files and `tool_spec.json`.

---

## 10. Product design doc fixes (`docs/LEDGERLENS_PRODUCT_DESIGN.md`, CRLF)

- **§7.5 output:** replace with §5's shape.
- **§7.5 queries:** replace with §6's three queries. The habit query is "Approved, same card, 90 days, excluding the charge". The location check is "closest event within ±2 h, conflict only for in-person channels".
- **§7.5 decline meanings:** add §3.1's table and the code-54 contradiction (D18).
- **Spec link:** add a line linking this spec.

---

## 11. Tests (`tests/unit/explain_transaction/`, pytest, TDD, no database or AWS)

| File | Covers |
|---|---|
| `test_decline_codes.py` | The four meanings verbatim; `IN_PERSON_CHANNELS == {"ATM", "POS", "Branch"}`. |
| `test_text_folding.py` | "México" and " MEXICO " fold equal; "São Paulo" folds to "sao paulo"; `None` stays `None`. |
| `test_explain_transaction_use_case.py` | Input cleaning; naive `as_of` rejected; each query gets exactly the §4 params; `charge_date` and `product_id` come from the core row. No core row → `TransactionNotFoundError`, and no other query runs. Each core failure → its domain error. Every row of the §3.4 table: `fx` same currency / different currency / NULL rate; `decline` per status, per code, and code-54 contradiction true/false/None; `usual_amount_range` with 2 vs 3 same-currency charges; `conflict` per channel, country fold and NULLs; `minutes_from_charge` sign. Habit failure → `None` + `unavailable`, and app activity still runs. App-activity failure → `None` + `unavailable`. No event row → `found: false`, not unavailable. NULL `transaction_date` → both in `unavailable`, and neither query runs. |
| `test_transaction_explanation_presenter.py` | The §5 shape; 2-decimal amounts; `rate` keeps its decimals; `{"found": false}` only; `null` sections; `unavailable` as names; **a recursive walk finds no key containing `fraud` or `score`**. |
| `test_explain_transaction_handler.py` | Success; both ids and `CLOCK.now()` reach the use case; validation, domain and unexpected errors; wrong tool name; `USE_CASE`/`CLOCK` `None`. |
| `test_query_contracts.py` | For each SQL file: placeholders match the params exactly; no stray `%`; no `SET`; mapped columns selected. **Neither `fraud_score` nor `is_fraud` appears in any SQL file.** `'Tarjeta Crédito'` and `'Approved'` are present, NFC, no BOM. The FX join uses `source_currency = t.currency` and `target_currency = p.currency`. The habit `translate()` mapping is identical on both sides, strips each accent correctly (the `list_card_transactions` test, copied), and matches `list_card_transactions.sql`'s strings. The app-activity window is `'2 hours'` on both sides. `tool_spec.json` requires `customer_id` and `transaction_id`, has exactly those two properties, and its description names `fx`, `decline`, `habit`, `app_activity` and `unavailable`. |
| `test_delivery_wiring.py` + the copied infrastructure tests | As in the fraud spec. |

The whole suite passes in one session: `.venv/Scripts/python -m pytest tests/unit -q`.

---

## 12. Risks

| # | Risk | Handling |
|---|---|---|
| R1, R3, R5–R13 | Same as the other tools | Copied TODO tags. R3 also covers `percentile_cont ... FILTER` and `bool_or` on DSQL. If DSQL rejects them, `habit` comes back unavailable and the rest still works. |
| X1 | **App activity is almost always empty** (D36), and digital events have no link to card activity. A `conflict` is a coincidence of synthetic streams. | The user kept it knowingly. The tool description says "usually not found; that's normal". It never feeds a verdict. |
| X2 | **No rate for some currencies.** The rates table covers ARS, COP, MXN and USD only, with no BRL. | `rate` and `amount_in_card_currency` are `null`, and the description says so. |
| X3 | **D17: status and code disagree** in places. | The decline section is shown only for `Declined`. The code is shown as stored. |
| X4 | **Code 54 contradicts the card state on about 12,020 declines** (D18). | `contradicts_card_state` says so plainly, so the agent doesn't tell the customer their card is expired. |
| X5 | **A past `AS_OF` shows the card's current expiration date.** | The same acceptance as session context C3. The contradiction compares with the charge date, which is what matters. |
