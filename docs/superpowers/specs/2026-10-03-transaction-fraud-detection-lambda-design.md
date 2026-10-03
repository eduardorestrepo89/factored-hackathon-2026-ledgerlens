# `transaction_fraud_detection` Lambda: Design

**Date:** 2026-10-03
**Status:** Draft, awaiting the user's review.
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7.6
**Layout rules:** [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md). One folder per tool, wrapping every layer. Code is copied between tools, never shared.
**Copied from:** `gateway/tools/get_session_context/` (see §9). It already has `ClockSettings` and `build_clock`.
**Siblings:** [explain_transaction](2026-10-03-explain-transaction-lambda-design.md) and [classify_call_type](2026-10-03-classify-call-type-lambda-design.md). Build order: this tool, then explain, then classify.

---

## 1. Goal

The tool tells the agent whether a credit-card charge is fraud. It works in two modes:

- **One charge** (`transaction_id`): one assessment.
- **Card sweep** (`card_last4`): every charge on that card in the last 30 days is checked. Only the ones flagged `fraud` or `review` come back, with a count of how many were checked.

The verdict comes from the `fraud_score` stored on each transaction. The dataset is treated as the feed of a bank fraud engine: the tool reads that engine's score and maps it to three bands. It adds no heuristic of its own.

### Success criteria
- A charge scored above 50 is `fraud`, above 30 up to 50 is `review`, and 30 or below (or no score) is `no_fraud` (§3).
- The raw score never leaves the Lambda. No output field, log line or error message contains it.
- No query reads `transactions.is_fraud` (DEC-10). A contract test enforces it.
- Credit cards only (`product_type = 'Tarjeta Crédito'`), matching `list_credit_cards`, `list_card_transactions` and `get_session_context`.
- A `transaction_id` or `card_last4` that doesn't belong to one of the customer's credit cards returns "not found". It never returns another customer's data.
- **Acceptance on the deployed stack** (`AS_OF = 2026-06-17T23:59:59`), customer P07 `CLI-EX6BOAOEFZHQ`:
  - `transaction_id = TRX-23BIJAU4GL46ATPW9STY` → `verdict: fraud`, `basis: scored`.
  - `card_last4 = 4497` → `checked: 3`, one flagged item, `TRX-23BIJAU4GL46ATPW9STY` with `fraud`.
  - `transaction_id = TRX-GQLHRNO8BSQEL5CYFBIQ` → `no_fraud`.
- Unit tests cover every layer with no database or AWS. `ruff format --check` and `ruff check` are clean. Nothing imports across tool folders.

### Decisions made with the user
| Topic | Decision |
|---|---|
| Source of the verdict | **The stored `fraud_score`** ("take the score that's stored in the database to detect fraud"). It's documented as a simulated fraud-engine feed. The tool adds no heuristic. |
| Bands | **50 / 30**, chosen by the user from the profiling. The scale is 0–100, not the 0–1 that §7.6 assumed. No non-fraud row scores above 30, so every row above 30 is fraud in the data. All 1,670 rows scored above 50 are fraud. 30–50 holds about 703 fraud rows and no clean ones. Below 30 the score has no signal. |
| Middle band | `review`: the agent asks whether the customer recognizes the charge, and if not, offers to open a case for clarification and dispute. |
| Raw score | Never returned. The agent sees the verdict and `basis` only. |
| Status | The verdict doesn't depend on `transaction_status`. A declined charge scored 62 is still `fraud`: someone tried. The status is returned so the agent can say "it was declined". |
| Sweep window | Last 30 days from `as_of`. The sweep returns only flagged items plus `checked`. |
| Input | Flat schema with both fields optional. "Exactly one of the two" is checked in domain validation, not with JSON Schema `oneOf`. |

### Out of scope
- Writing anything: blocking the card or opening a claim. The `next_step` text tells the agent what to offer. The actions belong to other tools.
- Using `explain_transaction`'s habit or location signals for the verdict. The user chose the stored score only.
- The Gateway target and the agent's prompt changes.

---

## 2. Layout

```
gateway/tools/transaction_fraud_detection/                  ← Lambda asset root for this tool only
├── tool_spec.json
├── requirements.txt                                        (copy)
└── transaction_fraud_detection_lambda/
    ├── __init__.py
    ├── domain/
    │   ├── value_objects/fraud_bands.py                    FraudVerdict, ScoreBasis, FRAUD_ABOVE,
    │   │                                                   REVIEW_ABOVE, NEXT_STEPS, assess()
    │   ├── value_objects/fraud_check_request.py            FraudCheckRequest.from_raw()
    │   ├── entities/fraud_assessment.py                    FraudAssessment, CardSweep
    │   └── errors.py
    ├── application/
    │   ├── ports/{database_repository,query_provider,errors}.py   (copy)
    │   └── use_cases/transaction_fraud_detection.py        TransactionFraudDetectionUseCase
    ├── infrastructure/
    │   ├── queries/file_query_provider.py                  (copy)
    │   └── repositories/dsql_repository.py                 (copy)
    ├── utils/connectors/{base,dsql}.py                     (copy)
    ├── delivery/
    │   ├── handler.py
    │   ├── settings.py                                     (copy, with ClockSettings)
    │   ├── dependencies/dependencies_builder.py            build_transaction_fraud_detection_use_case, build_clock
    │   └── presenters/fraud_assessment.py                  present_assessment, present_sweep
    └── queries/postgresql/
        ├── fraud_transaction.sql
        ├── fraud_card_exists.sql
        └── fraud_card_sweep.sql

tests/unit/transaction_fraud_detection/                     ← package (has __init__.py)
├── __init__.py, conftest.py, fakes.py
└── test_*.py
```

- **Handler string:** `transaction_fraud_detection_lambda/delivery/handler.handler`.
- **Tool name:** `transaction_fraud_detection`.
- **Lambda:** `ledgerlens-transaction-fraud-detection` (§7).

---

## 3. Domain

### 3.1 Bands (`domain/value_objects/fraud_bands.py`)

```python
FRAUD_ABOVE: Final = Decimal("50")
REVIEW_ABOVE: Final = Decimal("30")

class FraudVerdict(StrEnum):
    FRAUD = "fraud"
    REVIEW = "review"
    NO_FRAUD = "no_fraud"

class ScoreBasis(StrEnum):
    SCORED = "scored"          # the engine produced a score
    NOT_SCORED = "not_scored"  # fraud_score is NULL (about 20% of rows)

NEXT_STEPS: Final[Mapping[FraudVerdict, str | None]] = {
    FraudVerdict.FRAUD: "Confirm with the customer, then block the card and open a fraud claim.",
    FraudVerdict.REVIEW: "Ask whether they recognize the charge; if not, offer to open a case for clarification and dispute.",
    FraudVerdict.NO_FRAUD: None,
}

def assess(score: Decimal | None) -> tuple[FraudVerdict, ScoreBasis]: ...
```

| `score` | Result |
|---|---|
| `None` | `(NO_FRAUD, NOT_SCORED)` |
| `> 50` | `(FRAUD, SCORED)` |
| `> 30` and `<= 50` | `(REVIEW, SCORED)` |
| `<= 30` | `(NO_FRAUD, SCORED)` |

- The comparisons are strict, so exactly 50.00 is `review` and exactly 30.00 is `no_fraud`.
- A value outside 0–100 is banded as it is. The column is `numeric(5,2)`, and the profiling found none.
- The module docstring says that the score is a simulated fraud-engine feed, and that the bands come from the 2026-10-03 profiling (X3, X4, X15 in `datathon/analysis/profiling_output.txt`).
- **The bands are copied into `classify_call_type`** (its own copy, per the layout rules). Both tools' tests pin the literal values `50` and `30`, so changing one copy breaks a test.

### 3.2 Request (`domain/value_objects/fraud_check_request.py`)

```python
@dataclass(frozen=True)
class FraudCheckRequest:
    customer_id: str
    transaction_id: str | None
    card_last4: str | None

    @classmethod
    def from_raw(cls, event: object) -> "FraudCheckRequest": ...
```

| Input | Rule | Error |
|---|---|---|
| event not a JSON object | treated as `{}` | then `customer_id` fails |
| `customer_id` | non-empty string, stripped and uppercased | `InvalidInputError("customer_id", "is required and must be a non-empty string")` |
| `transaction_id` | `None`, or a non-empty string, stripped and uppercased. Blank counts as missing. | `InvalidInputError("transaction_id", "must be a non-empty string")` |
| `card_last4` | `None`, or exactly 4 ASCII digits after stripping. Blank counts as missing. | `InvalidInputError("card_last4", "must be exactly 4 digits")` |
| both given | — | `InvalidInputError("transaction_id", "give either transaction_id or card_last4, not both")` |
| neither given | — | `InvalidInputError("transaction_id", "give either transaction_id (one charge) or card_last4 (sweep of that card's last 30 days)")` |

Unknown keys are ignored. Validation runs before the database is touched.

### 3.3 Entities (`domain/entities/fraud_assessment.py`)

```python
@dataclass(frozen=True)
class FraudAssessment:
    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    verdict: FraudVerdict
    basis: ScoreBasis

@dataclass(frozen=True)
class CardSweep:
    card_last4: str
    date_from: datetime   # as_of - 30 days, inclusive
    date_to: datetime     # as_of
    checked: int
    flagged: tuple[FraudAssessment, ...]
    truncated: bool
```

`FraudAssessment` has no score field. The use case drops the score after calling `assess()`.

---

## 4. Use case (`application/use_cases/transaction_fraud_detection.py`)

```python
class TransactionFraudDetectionUseCase:
    SWEEP_DAYS: Final = 30

    def __init__(self, database_repository, query_provider, max_rows: int = 25): ...
    def execute(self, request: FraudCheckRequest, as_of: datetime) -> FraudAssessment | CardSweep: ...
```

- `max_rows < 1` raises `ValueError`. A naive `as_of` raises `ValueError` (a programming error). It's converted to naive UTC before binding (`as_of_sql`), as in `get_session_context`.

**One charge** (`request.transaction_id` set):
1. `fraud_transaction` with `customer_id`, `transaction_id`, `as_of`.
2. No row → `TransactionNotFoundError`.
3. Map the row, then `assess(row["fraud_score"])` → `FraudAssessment`.

**Card sweep** (`request.card_last4` set):
1. `fraud_card_exists` with `customer_id`, `card_last4`. No row → `CardNotFoundError`. Without this check a mistyped last4 would look like a clean card.
2. `fraud_card_sweep` with `customer_id`, `card_last4`, `as_of`, `review_above = REVIEW_ABOVE`, `limit = max_rows + 1`.
   - The query always returns at least one row. Each row carries `checked`, the window's total count, so one query returns both.
   - When nothing in the window scored above 30, the one row is **count-only**: its transaction columns are NULL and `checked` is the real count (0 for a card with no charges). Without this, a clean card with 3 charges would report `checked 0`.
   - `checked` comes from the first row. A row with a NULL `transaction_id` is count-only and isn't an item. No row at all is treated as `checked 0`.
3. Each item row gets `assess()`. The SQL already dropped rows at 30 or below, so every flagged item is `fraud` or `review`.
4. `truncated` is set when `max_rows + 1` item rows come back. The extra row is dropped.

**Errors** (in both modes, any query):
- `DataSourceConnectionError` → `DataSourceUnavailableError`.
- Any other `DataAccessError` → `FraudCheckLookupError`.
- A mapping error (`KeyError`, `TypeError`, `ValueError`, including `checked` not an int) → `FraudCheckDataIntegrityError`.

**Params each query gets** (each key must match a placeholder, and vice versa):

| Query | Params |
|---|---|
| `fraud_transaction` | `customer_id`, `transaction_id`, `as_of` |
| `fraud_card_exists` | `customer_id`, `card_last4` |
| `fraud_card_sweep` | `customer_id`, `card_last4`, `as_of`, `review_above`, `limit` |

The mapping helpers are copied from `get_session_context` (`_optional_text`, `_optional_amount`, `_optional_datetime`, `_optional_int`). There's one new helper, `_optional_score`: a `Decimal`, `int` or `None` passes, and anything else raises `TypeError`.

---

## 5. Output to the agent (`delivery/presenters/fraud_assessment.py`)

One charge:

```json
{
  "mode": "transaction",
  "assessment": {
    "transaction_id": "TRX-23BIJAU4GL46ATPW9STY",
    "transaction_date": "2026-05-31T06:09:15",
    "card_last4": "4497",
    "merchant_name": "Estación de Servicio",
    "amount": "288.69",
    "currency": "USD",
    "transaction_status": "Approved",
    "verdict": "fraud",
    "basis": "scored",
    "next_step": "Confirm with the customer, then block the card and open a fraud claim."
  }
}
```

Card sweep:

```json
{
  "mode": "card",
  "card_last4": "4497",
  "date_from": "2026-05-18T23:59:59",
  "date_to": "2026-06-17T23:59:59",
  "checked": 3,
  "flagged": [ { "...": "same shape as assessment" } ],
  "truncated": false
}
```

- Amounts are 2-decimal strings (half-up), as in the other tools. Timestamps use ISO 8601 with no time zone, matching `list_card_transactions`.
- `next_step` is `null` for `no_fraud`.
- `flagged` is sorted by score descending, then `transaction_date` descending, then `transaction_id`. The sort happens in SQL, so the score never reaches Python's output. A truncated sweep therefore keeps the `fraud` items and drops the lowest `review` ones.
- **The output never has a `fraud_score`, `score` or `is_fraud` key.** A presenter test walks the whole JSON and checks this.

### 5.1 `tool_spec.json`

```json
[
  {
    "name": "transaction_fraud_detection",
    "description": "Checks whether a credit-card charge is fraud, using the bank's fraud engine. Give exactly one of transaction_id (checks that charge) or card_last4 (checks every charge on that card in the last 30 days and returns only the flagged ones, with 'checked' = how many were looked at). Each assessment has a verdict: 'fraud' (confirm with the customer, then block the card and open a fraud claim), 'review' (ask whether they recognize the charge; if not, offer to open a case for clarification and dispute) or 'no_fraud'. 'next_step' says what to offer. basis 'not_scored' means the engine produced no score for that charge; it isn't proof the charge is genuine. Never tell the customer a score: none is returned. Amounts are strings with 2 decimals in the charge's currency.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's ID from SESSION CONTEXT." },
        "transaction_id": { "type": "string", "description": "One charge to check, e.g. TRX-23BIJAU4GL46ATPW9STY. Leave out when giving card_last4." },
        "card_last4": { "type": "string", "description": "Last 4 digits of one of the customer's credit cards, to sweep its last 30 days. Leave out when giving transaction_id." }
      },
      "required": ["customer_id"]
    }
  }
]
```

---

## 6. SQL (`queries/postgresql/`)

All three use psycopg named placeholders. They have no `%` outside placeholders, no `SET`, and the `'Tarjeta Crédito'` literal in NFC UTF-8 with no BOM. `DISTINCT ON` removes duplicate rows (R8). Each has the header-comment style of `list_card_transactions.sql` and the R3/R8 TODO tags.

### 6.1 `fraud_transaction.sql`
```sql
SELECT DISTINCT ON (t.transaction_id)
       t.transaction_id, t.transaction_date,
       RIGHT(p.product_number, 4) AS card_last4,
       t.merchant_name, t.amount, t.currency, t.transaction_status,
       t.fraud_score
FROM transactions AS t
JOIN products AS p ON p.product_id = t.product_id
WHERE t.transaction_id = %(transaction_id)s
  AND t.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND t.transaction_date <= %(as_of)s
ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
```
- `customer_id` in the `WHERE` is the ownership check. Another customer's ID, or a debit-card charge, gives no row, and the result is "not found".
- `transaction_date <= as_of` keeps the demo's "now" honest.

### 6.2 `fraud_card_exists.sql`
```sql
SELECT 1 AS card_exists
FROM products AS p
WHERE p.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND RIGHT(p.product_number, 4) = %(card_last4)s
LIMIT 1
```
A card in any status counts. A blocked card's charges can still be fraud.

### 6.3 `fraud_card_sweep.sql`
```sql
WITH window_tx AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.transaction_date,
           RIGHT(p.product_number, 4) AS card_last4,
           t.merchant_name, t.amount, t.currency, t.transaction_status,
           t.fraud_score
    FROM transactions AS t
    JOIN products AS p ON p.product_id = t.product_id
    WHERE t.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
      AND RIGHT(p.product_number, 4) = %(card_last4)s
      AND t.process_date >= (%(as_of)s::date - 31)
      AND t.transaction_date >= %(as_of)s - INTERVAL '30 days'
      AND t.transaction_date <= %(as_of)s
    ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
),
totals AS (
    SELECT COUNT(*) AS checked FROM window_tx
),
flagged AS (
    SELECT * FROM window_tx
    WHERE fraud_score > %(review_above)s::numeric
    ORDER BY fraud_score DESC, transaction_date DESC NULLS LAST, transaction_id
    LIMIT %(limit)s
)
SELECT f.transaction_id, f.transaction_date, f.card_last4, f.merchant_name,
       f.amount, f.currency, f.transaction_status, f.fraud_score, totals.checked
FROM totals
LEFT JOIN flagged AS f ON TRUE
ORDER BY f.fraud_score DESC NULLS LAST, f.transaction_date DESC NULLS LAST,
         f.transaction_id
```
- The window filters on `transaction_date`, and the lower bound is inclusive. `process_date` is only there for partition pruning (product design §8.1). Its extra day covers charges processed a day later.
- `checked` counts every de-duplicated charge in the window, including those with no score. `totals` always has one row, and the `LEFT JOIN` keeps it when nothing is flagged: that gives the count-only row (§4).
- The outer `ORDER BY` repeats the flagged order, because a join doesn't keep a CTE's order.
- `review_above` comes from the domain constant, so the band lives in one place in this tool.
- A card that has two products with the same last 4 digits (one replaced, say) is swept across both. That's correct, since the customer sees one last4.

---

## 7. CDK (`infra-cdk/lib/data-construct.ts`)

This change needs the user's approval. Approving this spec approves it.

- Add `{ tool: "transaction_fraud_detection", id: "TransactionFraudDetection" }` to the `tools` array. This gives the function `ledgerlens-transaction-fraud-detection` and the log group `/aws/lambda/<stack_name_base>-transaction-fraud-detection`. The loop already sets the VPC, role, `DSQL_CLUSTER_ENDPOINT` and `AS_OF`.
- `infra-cdk/test/data-construct.test.ts`:
  - The `vpcFns` count goes from 4 to 5. The sibling specs take it to 6 and 7.
  - Add a `test.each` row `["transaction_fraud_detection", "ledgerlens-transaction-fraud-detection"]`.
- Deploy with `npx cdk deploy ledgerlens-bank-assistant-data --exclusively --require-approval never --profile ledgerlens`, then run the §1 acceptance checks with `aws lambda invoke` and the client context `target___transaction_fraud_detection`.

---

## 8. Errors

### 8.1 Port errors
Copied as they are: `DataAccessError`, `DataSourceConnectionError`, `QueryExecutionError`, `QueryLimitExceededError`, `QueryNotFoundError`.

### 8.2 Domain errors (`domain/errors.py`)
`DomainError`, `InvalidInputError` and `_FixedMessageError` are copied. This tool's fixed-message errors:

| Cause | Domain error | Message |
|---|---|---|
| no transaction row | `TransactionNotFoundError` | "No credit-card charge with this transaction_id belongs to this customer. Don't guess; ask the customer to confirm the charge, or call list_card_transactions to find it." |
| no card row | `CardNotFoundError` | "None of this customer's credit cards ends in these 4 digits. Call list_credit_cards to see their cards and ask which one they mean." |
| `DataSourceConnectionError` | `DataSourceUnavailableError` | "The fraud check is temporarily unavailable. Offer to retry in a moment or hand off to a human agent; if the customer reports a charge they don't recognize, offer the hand-off now." |
| any other `DataAccessError` | `FraudCheckLookupError` | "The fraud check can't run right now due to an internal error. Don't retry; offer a hand-off to a human agent." |
| mapping failure | `FraudCheckDataIntegrityError` | "The fraud check came back in an unexpected format. Don't retry; offer a hand-off to a human agent." |

### 8.3 Handler (`delivery/handler.py`)
Copied from `get_session_context`, then changed:
- `TOOL_NAME = "transaction_fraud_detection"`.
- `request = FraudCheckRequest.from_raw(event)` inside the `try`, so an `InvalidInputError` becomes `{"error": message}`.
- `result = USE_CASE.execute(request, as_of=CLOCK.now())`, then `present_assessment` or `present_sweep` by type.
- The log line is `"%s mode=%s verdict_counts=%s"`. It never logs scores or customer data.
- The unexpected-error text is "Unexpected internal error running the fraud check. Offer a hand-off to a human agent."

Everything else is unchanged: the wrong-tool-name guard, the `USE_CASE is None or CLOCK is None` guard, `DomainError` → `{"error": message}`, any other exception → the generic message, never `str(e)`.

---

## 9. Copy list

Each file below is copied from `gateway/tools/get_session_context/get_session_context_lambda/`. Every `get_session_context_lambda` import becomes `transaction_fraud_detection_lambda`.

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
| `delivery/handler.py` | §8.3 |
| `domain/errors.py` | Fixed-message errors replaced (§8.2) |

New files: `fraud_bands.py`, `fraud_check_request.py`, `fraud_assessment.py` (entities), the use case, the presenter, the three SQL files and `tool_spec.json`.

---

## 10. Product design doc fixes (`docs/LEDGERLENS_PRODUCT_DESIGN.md`, CRLF)

§7.6 changes as follows:
- **Description:** use the §5.1 description.
- **Output:** use the §5 shapes.
- **Logic table:** replace with the bands from §3.1. Add a note that `fraud_score` is 0–100 and that the 0.7/0.4 thresholds were wrong. The location and habit conditions are dropped: the verdict uses the stored score only (user decision, 2026-10-03).
- **Spec link:** add a line linking this spec.

Keep line endings CRLF.

---

## 11. Tests (`tests/unit/transaction_fraud_detection/`, pytest, TDD, no database or AWS)

The folder is a package. `conftest.py` puts `gateway/tools/transaction_fraud_detection` on `sys.path`. `fakes.py` (adapted from `get_session_context`) holds a fake repository that answers by query name and can raise per query, plus row builders.

| File | Covers |
|---|---|
| `test_fraud_bands.py` | `FRAUD_ABOVE == Decimal("50")` and `REVIEW_ABOVE == Decimal("30")` (pinned literals); every row of the §3.1 table, including exactly 50.00, 50.01, 30.00, 30.01 and `None`; `NEXT_STEPS` text per verdict, with `None` for `no_fraud`. |
| `test_fraud_check_request.py` | Every row of the §3.2 table; stripping and uppercasing; `" 4497 "` accepted; `"449"`, `"44a7"`, `"٤٤٩٧"` (non-ASCII digits) rejected; unknown keys ignored; a non-object event. |
| `test_transaction_fraud_detection_use_case.py` | Each mode sends exactly the §4 params, with naive UTC `as_of` (an aware `-05:00` input is converted). `review_above` is the domain constant. No transaction row → `TransactionNotFoundError`. No card row → `CardNotFoundError`, and the sweep query never runs. Sweep with no rows → `checked 0`, empty `flagged`. A count-only row (NULL `transaction_id`, `checked 3`) → `checked 3`, empty `flagged`. `checked` comes from the rows. Truncation (26 → 25, `truncated`). Each port error → its domain error. A bad row (`fraud_score` a string, `checked` missing) → `FraudCheckDataIntegrityError`. `max_rows < 1` and naive `as_of` rejected. |
| `test_fraud_assessment_presenter.py` | Both shapes; 2-decimal half-up amounts; `None` → `null`; `next_step` per verdict; **a recursive walk finds no `fraud_score`, `score` or `is_fraud` key**. |
| `test_transaction_fraud_detection_handler.py` | Success in both modes; `CLOCK.now()` reaches the use case; validation errors → `{"error": message}`; domain error → message; unexpected exception → generic message; wrong tool name; `USE_CASE` or `CLOCK` `None` → unavailable message. |
| `test_query_contracts.py` | For each of the 3 SQL files: placeholders match the use case's params exactly; no stray `%`; no `SET`; every mapped column selected; **`is_fraud` appears in no SQL file**; `'Tarjeta Crédito'` is present, NFC UTF-8, no BOM; the sweep orders by `fraud_score DESC` and filters `> %(review_above)s`. `tool_spec.json` is valid, named `transaction_fraud_detection`, requires only `customer_id`, has exactly the three properties, and its description names `fraud`, `review`, `no_fraud`, `not_scored`, `checked` and "30 days". |
| `test_delivery_wiring.py` | The builder blocks; `build_clock`; the use case wired end to end over a fake connector; `MAX_ROWS` honoured; bad configuration → `None`. |
| `test_errors.py`, `test_settings.py`, `test_file_query_provider.py`, `test_dsql_repository.py`, `test_psycopg_connector.py`, `test_dsql_connector.py` | Copied with imports changed. |

The CDK test (`data-construct.test.ts`) changes as described in §7.

**The whole suite must pass in one session:** `.venv/Scripts/python -m pytest tests/unit -q`. Use the same `--ignore` flags the other tool runs need while `duckdb` and `aurora_dsql_psycopg` are missing from `.venv`.

---

## 12. Risks

| # | Risk | Handling |
|---|---|---|
| R1, R3, R5–R13 | Same as the other tools (SQL untested on DSQL before deploy; trusted `customer_id`; DSQL connection and packaging notes) | Copied TODO tags. R3 is checked by the §1 acceptance run. |
| F1 | **The score is synthetic.** The bands fit this dataset (everything above 30 is fraud), not a real engine. | It's documented in `fraud_bands.py` and in §10. A real engine would bring its own bands. |
| F2 | **About 20% of charges have no score.** A `not_scored` fraud charge comes back `no_fraud`. | `basis: not_scored` and the tool description say it isn't proof. Profiling shows a 0.1% fraud rate among unscored rows. |
| F3 | **The bands are copied into `classify_call_type`.** | Both tools' tests pin `50` and `30`. |
| F4 | **The sort exposes relative score order** in `flagged`. | This is harmless: no value is shown, and the agent only sees the verdict. |
| R8 | Duplicate rows | `DISTINCT ON` in every query. |
