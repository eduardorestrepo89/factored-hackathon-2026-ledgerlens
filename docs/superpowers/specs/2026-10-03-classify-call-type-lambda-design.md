# `classify_call_type` Lambda: Design

**Date:** 2026-10-03
**Status:** Draft, awaiting the user's review.
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7.2. This spec departs from it in places; §10 lists each departure.
**Layout rules:** [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md). One folder per tool, wrapping every layer. Code is copied between tools, never shared.
**Copied from:** `gateway/tools/get_session_context/` (see §9). The fraud bands are copied from `transaction_fraud_detection`.
**Siblings:** [transaction_fraud_detection](2026-10-03-transaction-fraud-detection-lambda-design.md) and [explain_transaction](2026-10-03-explain-transaction-lambda-design.md). Build order: fraud, explain, then this tool.

---

## 1. Goal

The tool ranks up to 3 likely reasons the customer is contacting the bank right now. Each reason comes with a confidence, the record it points to, and evidence. The agent uses the list to open the conversation ("I see a declined charge yesterday at…") instead of asking a cold "how can I help?".

### Success criteria
- It returns at most 3 reasons, best first. An empty list is a valid answer.
- Each query feeds a fixed set of reasons. A failed query makes those reasons `unavailable`, and the others are still ranked. Only a failure of all four queries fails the call.
- Weights, decay and ranking live in Python domain code, with unit tests. SQL only fetches candidates.
- The raw fraud score never leaves the Lambda. `evidence` never contains it. No query reads `is_fraud` (DEC-10).
- Credit cards only, as in the other tools.
- **Acceptance on the deployed stack** (`AS_OF = 2026-06-17T23:59:59`):

  | Persona | Expected |
  |---|---|
  | P07 `CLI-EX6BOAOEFZHQ` | `FRAUD_SUSPECTED` first, `ref_id` `TRX-23BIJAU4GL46ATPW9STY`, confidence 0.77 (95 − 17.74 days = 77.26) |
  | P01 `CLI-1GL7QBDG3QG0` | `DECLINED_TRANSACTION` first, `TRX-SSJAIUCVVU1L4605ZLNM`, 0.79 (code 51, 5.58 h old) |
  | P02 `CLI-7EC6UCDZMSKV` | `PENDING_TRANSACTION` first, `TRX-M8SV89D2QGIE6WRUB79K`, 0.61. The `Closed` card 4364 adds nothing. |
  | P03 `CLI-70U0WJ1NH1MN` | `REVERSED_TRANSACTION` first, `TRX-LJGEBUAOX0G4CL4RQSIU`, 0.26 (44.4 h old, at the 40% floor) |
  | P05 `CLI-50OIF5EIYSWK` | `FOREIGN_TRANSACTION` first, `TRX-MQKFELIPWT098DXTN2WN` (Brazil), 0.44. The code-14 decline (2026-06-14 16:03) is 80 h before `AS_OF`, outside the 72 h window, so there's **no** `DECLINED_TRANSACTION`. |
  | P08 `CLI-GG3Z1440277M` | `OPEN_CASE_FOLLOWUP` first, `CMP-FHCLR8TGWMBD0YFOCLYS`, 0.60 (`sla_breached` NULL counts as not breached) |
  | P10 `CLI-Z3V3SBS18YWQ` | `CARD_NOT_ACTIVE` (7718, Blocked) 0.60, then `PAYMENT_OVERDUE` (2626, 180 days) 0.50 |

- Unit tests cover every layer with no database or AWS. `ruff` is clean. Nothing imports across tool folders.

### Decisions made with the user
| Topic | Decision |
|---|---|
| Fraud score | **Classify uses the stored `fraud_score`, with the same 50/30 bands as `transaction_fraud_detection`.** The original brainstorm framing said classify shouldn't use the score and that fraud detection should reuse classify's logic. The user later chose the opposite: fraud detection reads the stored score ("take the score that's stored in the database"), and classify ranks the two bands as two reasons. |
| Two fraud reasons | **`FRAUD_SUSPECTED`** (above 50) and **`UNRECOGNIZED_CHARGE_REVIEW`** (above 30 up to 50). Both are Approved only and cover 30 days. |
| Status asymmetry | `transaction_fraud_detection` ignores status: a declined attempt can still be fraud. Classify's fraud reasons require `Approved`, because the reason for the call is money that left. A declined charge is already `DECLINED_TRANSACTION`, with its own higher-urgency wording. This is deliberate, not a contradiction. |
| Taxonomy | The 11 reasons in §3.1. They replace §7.2's 7. |
| Construction | Four candidate queries, with weights, decay and ranking in Python. The evidence object is built in the presenter. |
| P05 acceptance | **FOREIGN_TRANSACTION only** (user, 2026-10-03). Its code-14 decline is 80 h old, outside the 72 h window, and the window stays at 72 h to match `get_session_context`. |

### Out of scope
- **Calling the tool automatically at session start** (product design §6). That's an agent change and gets its own follow-up. Until then the agent calls the tool itself.
- Learning weights from data (DEC-10: the score is shown, never learned from).
- The Gateway target.

---

## 2. Layout

```
gateway/tools/classify_call_type/                           ← Lambda asset root for this tool only
├── tool_spec.json
├── requirements.txt                                        (copy)
└── classify_call_type_lambda/
    ├── __init__.py
    ├── domain/
    │   ├── value_objects/fraud_bands.py                    FRAUD_ABOVE, REVIEW_ABOVE (copied from the fraud tool)
    │   ├── value_objects/call_reasons.py                   CallReason, Decay, REASON_RULES, SOURCE_REASONS
    │   ├── value_objects/text_folding.py                   fold_text() (copied from explain_transaction)
    │   ├── entities/candidates.py                          TransactionCandidate, CardCandidate,
    │   │                                                   CaseCandidate, AppEventCandidate
    │   ├── entities/call_classification.py                 RankedReason, CallClassification
    │   ├── services/reason_ranking.py                      detect_*(), score(), rank()
    │   └── errors.py
    ├── application/
    │   ├── ports/{database_repository,query_provider,errors}.py   (copy)
    │   └── use_cases/classify_call_type.py                 ClassifyCallTypeUseCase
    ├── infrastructure/ …                                   (copy)
    ├── utils/connectors/{base,dsql}.py                     (copy)
    ├── delivery/
    │   ├── handler.py
    │   ├── settings.py                                     (copy, with ClockSettings)
    │   ├── dependencies/dependencies_builder.py            build_classify_call_type_use_case, build_clock
    │   └── presenters/call_classification.py               present_call_classification (builds evidence)
    └── queries/postgresql/
        ├── call_reason_transactions.sql
        ├── call_reason_cards.sql
        ├── call_reason_cases.sql
        └── call_reason_app_events.sql

tests/unit/classify_call_type/                              ← package (has __init__.py)
```

- **Handler string:** `classify_call_type_lambda/delivery/handler.handler`.
- **Tool name:** `classify_call_type`.
- **Lambda:** `ledgerlens-classify-call-type` (§7).

---

## 3. Domain

### 3.1 Reasons (`domain/value_objects/call_reasons.py`)

The enum is in this order, which is also the final tie-break:

| `CallReason` | Signal (all credit cards only) | Window from `as_of` | Weight | Decay | `ref_id` |
|---|---|---|---:|---|---|
| `FRAUD_SUSPECTED` | `Approved` and `fraud_score > 50` | 30 days | 95 | per day | `transaction_id` |
| `DECLINED_TRANSACTION` | `Declined` | 72 hours | 85 | per hour | `transaction_id` |
| `UNRECOGNIZED_CHARGE_REVIEW` | `Approved` and `30 < fraud_score <= 50` | 30 days | 70 | per day | `transaction_id` |
| `OPEN_CASE_FOLLOWUP` | Complaint open at `as_of` | any age | 75 if `sla_breached` is true, else 60 (NULL counts as false) | none | `complaint_id` |
| `PENDING_TRANSACTION` | `Pending` | 72 hours | 65 | per hour | `transaction_id` |
| `REVERSED_TRANSACTION` | `Reversed` | 72 hours | 65 | per hour | `transaction_id` |
| `CARD_NOT_ACTIVE` | `product_status` in {`Blocked`, `Suspended`} | state | 60 | none | `card_last4` |
| `FAILED_APP_ACTION` | Digital event with `event_type = 'Error'` | 24 hours | 60 | per hour | `event_id` |
| `FOREIGN_TRANSACTION` | `Approved`, and the country differs from the customer's home country (folded) **or** the charge currency differs from the card's | 72 hours | 55 | per hour | `transaction_id` |
| `PAYMENT_OVERDUE` | `product_status = 'Active'` and `days_past_due > 0` | state | 50 | none | `card_last4` |
| `CARD_EXPIRING` | `product_status = 'Active'`, and `expiration_date` between `as_of`'s date and that date + 30 days, inclusive | state | 35 | none | `card_last4` |

- **Windows** are on `transaction_date` or `event_date`, with `as_of - window <= date <= as_of`.
- **`Closed` cards** don't trigger `CARD_NOT_ACTIVE`: a closed card isn't a reason to call about the card.
- **FOREIGN country check:** `fold_text(transaction_country) != fold_text(home_country)` when both are non-NULL. "México" equals "Mexico" (D21).
- **FOREIGN currency check:** both currencies non-NULL and different.
- **One charge can trigger several reasons.** An approved Brazilian charge scored 62 is both `FRAUD_SUSPECTED` and `FOREIGN_TRANSACTION`. Each reason is ranked on its own.

### 3.2 Scoring (`domain/services/reason_ranking.py`)

```
age_hours = max((as_of - event_time).total_seconds() / 3600, 0)
per hour:  score = max(weight - age_hours,      0.4 * weight)
per day:   score = max(weight - age_hours / 24, 0.4 * weight)
none:      score = weight
confidence = Decimal(score / 100) rounded to 2 places, half-up
```

- The arithmetic uses `Decimal` throughout. Age is fractional (17.74 days, not 17).
- An event with a NULL date never becomes a candidate for a timed reason.
- **The best event per reason** has the highest score. Ties go to the newest event, then the lowest `ref_id`. State reasons have no event time, so ties go to the lowest `ref_id`.
- **Ranking across reasons:** unrounded score descending, then weight descending, then enum order. The top 3 are kept.

### 3.3 Sources (`SOURCE_REASONS`)

| Query (`Source`) | Reasons it feeds |
|---|---|
| `transactions` | `FRAUD_SUSPECTED`, `DECLINED_TRANSACTION`, `UNRECOGNIZED_CHARGE_REVIEW`, `PENDING_TRANSACTION`, `REVERSED_TRANSACTION`, `FOREIGN_TRANSACTION` |
| `cards` | `CARD_NOT_ACTIVE`, `PAYMENT_OVERDUE`, `CARD_EXPIRING` |
| `cases` | `OPEN_CASE_FOLLOWUP` |
| `app_events` | `FAILED_APP_ACTION` |

A test checks that every reason appears exactly once.

### 3.4 Entities

```python
@dataclass(frozen=True)
class TransactionCandidate:
    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    card_currency: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    response_code: str | None
    transaction_country: str | None
    home_country: str | None
    fraud_score: Decimal | None      # used for banding only; never presented

@dataclass(frozen=True)
class CardCandidate:  card_last4, product_status, expiration_date, days_past_due
@dataclass(frozen=True)
class CaseCandidate:  complaint_id, case_type, category, subcategory, status, sla_breached, days_open
@dataclass(frozen=True)
class AppEventCandidate: event_id, event_date, page_title, action

@dataclass(frozen=True)
class RankedReason:
    reason: CallReason
    confidence: Decimal
    ref_id: str
    candidate: TransactionCandidate | CardCandidate | CaseCandidate | AppEventCandidate

@dataclass(frozen=True)
class CallClassification:
    reasons: tuple[RankedReason, ...]       # 0 to 3
    unavailable: tuple[CallReason, ...]     # enum order
```

---

## 4. Use case (`application/use_cases/classify_call_type.py`)

```python
class ClassifyCallTypeUseCase:
    TOP_N: Final = 3
    TRANSACTION_CANDIDATE_CAP: Final = 200

    def __init__(self, database_repository, query_provider): ...
    def execute(self, customer_id: object, as_of: datetime) -> CallClassification: ...
```

1. Clean `customer_id` (copied `_clean_customer_id`). `as_of` must be aware, and is converted to naive UTC.
2. Run the four queries one after another, in `Source` order, each in its own `try`. A `DataAccessError` or mapping error adds that source's reasons to `unavailable` and logs a warning. The other sources still run.
3. **If all four fail**, raise:
   - `DataSourceUnavailableError` when any of the failures was a `DataSourceConnectionError`;
   - otherwise `CallReasonLookupError`.
4. Detect candidates per reason (§3.1), score them, keep the best per reason, and rank (§3.2).
5. If the transactions query returns more than `TRANSACTION_CANDIDATE_CAP` rows, log a warning and rank the rows that came back. The SQL orders newest first, so the oldest are dropped.

An unknown customer gets four empty results and `reasons: []`. The tool doesn't look the customer up. `get_session_context` already did that at session start.

**Params each query gets:**

| Query | Params |
|---|---|
| `call_reason_transactions` | `customer_id`, `as_of`, `review_above`, `limit` (`TRANSACTION_CANDIDATE_CAP + 1`) |
| `call_reason_cards` | `customer_id` |
| `call_reason_cases` | `customer_id`, `as_of` |
| `call_reason_app_events` | `customer_id`, `as_of` |

---

## 5. Output to the agent (`delivery/presenters/call_classification.py`)

```json
{
  "reasons": [
    {
      "reason": "FRAUD_SUSPECTED",
      "confidence": 0.77,
      "ref_id": "TRX-23BIJAU4GL46ATPW9STY",
      "evidence": {
        "transaction_date": "2026-05-31T06:09:15",
        "card_last4": "4497",
        "merchant_name": "Estación de Servicio",
        "amount": "288.69",
        "currency": "USD",
        "transaction_status": "Approved"
      }
    }
  ],
  "unavailable": []
}
```

`confidence` is a JSON number with 2 decimals.

**`evidence` keys by reason:**

| Reason | Keys |
|---|---|
| `FRAUD_SUSPECTED`, `UNRECOGNIZED_CHARGE_REVIEW`, `PENDING_TRANSACTION`, `REVERSED_TRANSACTION` | `transaction_date`, `card_last4`, `merchant_name`, `amount`, `currency`, `transaction_status` |
| `DECLINED_TRANSACTION` | the same, plus `response_code` |
| `FOREIGN_TRANSACTION` | the same as the first row, plus `transaction_country`, `home_country`, `card_currency` |
| `OPEN_CASE_FOLLOWUP` | `case_type`, `category`, `subcategory`, `status`, `sla_breached`, `days_open` |
| `CARD_NOT_ACTIVE` | `card_last4`, `product_status` |
| `PAYMENT_OVERDUE` | `card_last4`, `days_past_due` |
| `CARD_EXPIRING` | `card_last4`, `expiration_date`, `days_left` (expiration date minus `as_of`'s date) |
| `FAILED_APP_ACTION` | `event_date`, `page_title`, `action` |

- Evidence is a structured object, not §7.2's formatted string. The agent words it in the customer's language.
- **No key anywhere in the output contains `fraud` or `score`.** A presenter test walks the JSON. A reason's name may contain "FRAUD", because that's a value, not a key.

### 5.1 `tool_spec.json`

```json
[
  {
    "name": "classify_call_type",
    "description": "Ranks up to 3 likely reasons the customer is contacting the bank right now, best first, each with a confidence from 0 to 1, the record it points to (ref_id: a transaction_id, complaint_id, event_id or card last4) and evidence. Reasons: FRAUD_SUSPECTED (the fraud engine flagged an approved charge in the last 30 days), UNRECOGNIZED_CHARGE_REVIEW (a charge the engine wants the customer to confirm), DECLINED_TRANSACTION, PENDING_TRANSACTION and REVERSED_TRANSACTION (last 72 hours), OPEN_CASE_FOLLOWUP, CARD_NOT_ACTIVE (blocked or suspended card), FAILED_APP_ACTION (an app or web error in the last 24 hours), FOREIGN_TRANSACTION (approved charge abroad or in another currency, last 72 hours), PAYMENT_OVERDUE, CARD_EXPIRING (within 30 days). These are hypotheses to open the conversation with, not facts: confirm with the customer. An empty list means nothing stands out; ask how you can help. 'unavailable' names reasons that couldn't be checked. Call it at the start of the conversation.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's ID from SESSION CONTEXT." }
      },
      "required": ["customer_id"]
    }
  }
]
```

---

## 6. SQL (`queries/postgresql/`)

The conventions are the same as the sibling specs.

### 6.1 `call_reason_transactions.sql`
```sql
WITH tx_dedup AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.transaction_date,
           RIGHT(p.product_number, 4) AS card_last4,
           p.currency                 AS card_currency,
           t.merchant_name, t.amount, t.currency, t.transaction_status,
           t.response_code, t.transaction_country, t.fraud_score
    FROM transactions AS t
    JOIN products AS p ON p.product_id = t.product_id
    WHERE t.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
      AND t.process_date >= (%(as_of)s::date - 31)
      AND t.transaction_date >= %(as_of)s - INTERVAL '30 days'
      AND t.transaction_date <= %(as_of)s
    ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
),
home AS (
    SELECT c.country FROM customers AS c
    WHERE c.customer_id = %(customer_id)s
    ORDER BY c.last_updated DESC NULLS LAST
    LIMIT 1
)
SELECT x.*, h.country AS home_country
FROM tx_dedup AS x
LEFT JOIN home AS h ON TRUE
WHERE x.transaction_date >= %(as_of)s - INTERVAL '72 hours'
   OR (x.transaction_status = 'Approved' AND x.fraud_score > %(review_above)s::numeric)
ORDER BY x.transaction_date DESC NULLS LAST, x.transaction_id
LIMIT %(limit)s
```
- The SQL only narrows the candidates: everything in the last 72 hours, plus 30-day approved charges above the review band. Python applies every reason rule, including the windows again, so the rules have one owner.
- `review_above` comes from the copied domain constant.

### 6.2 `call_reason_cards.sql`
This is `session_credit_cards.sql`'s de-duplicated card query. It returns `card_last4`, `product_status`, `expiration_date` and `days_past_due`, and has no `LIMIT`, because a customer has a handful of cards.

### 6.3 `call_reason_cases.sql`
This is `session_open_cases.sql`'s open-at-`as_of` filter and de-duplication, returning the `CaseCandidate` columns. `days_open` is `as_of::date - creation_date::date`. There's no `LIMIT`. Only the best case is used, and the sort is `sla_breached DESC`, then newest first.

### 6.4 `call_reason_app_events.sql`
```sql
SELECT e.event_id, e.event_date, e.page_title, e.action
FROM digital_events AS e
WHERE e.customer_id = %(customer_id)s
  AND e.event_type = 'Error'
  AND e.process_date >= (%(as_of)s::date - 1)
  AND e.event_date >  %(as_of)s - INTERVAL '24 hours'
  AND e.event_date <= %(as_of)s
ORDER BY e.event_date DESC NULLS LAST, e.event_id
LIMIT 50
```
This uses the same `'Error'` mapping as `session_digital_signals.sql`'s `FAILED_ACTION`.

---

## 7. CDK (`infra-cdk/lib/data-construct.ts`)

This change needs the user's approval. Approving this spec approves it.

- Add `{ tool: "classify_call_type", id: "ClassifyCallType" }` to the `tools` array. This gives the function `ledgerlens-classify-call-type`.
- `data-construct.test.ts`:
  - The `vpcFns` count goes up by one: 7 after fraud and explain.
  - Add a `test.each` row `["classify_call_type", "ledgerlens-classify-call-type"]`.
- Deploy with the same command, then run the §1 acceptance table with the client context `target___classify_call_type`.

---

## 8. Errors

| Cause | Domain error | Message |
|---|---|---|
| all four queries failed, at least one on the connection | `DataSourceUnavailableError` | "Call reasons are temporarily unavailable. Greet the customer and ask how you can help." |
| all four failed, none on the connection | `CallReasonLookupError` | "Call reasons can't be computed right now due to an internal error. Don't retry; greet the customer and ask how you can help." |
| bad `customer_id` | `InvalidInputError` (copied) | "customer_id is required and must be a non-empty string" (the copied format) |

The handler is copied from `get_session_context`, with these changes:
- `TOOL_NAME = "classify_call_type"`.
- `present_call_classification(USE_CASE.execute(customer_id, as_of=CLOCK.now()))`.
- It logs the reason names and `unavailable`, never evidence or scores.
- The unexpected-error text is "Unexpected internal error ranking call reasons. Greet the customer and ask how you can help."

---

## 9. Copy list

These are copied from `get_session_context_lambda/` with the import changes, as in the fraud spec's §9: `requirements.txt`, the `__init__.py` files, ports, `file_query_provider.py`, `dsql_repository.py`, the connectors, `settings.py`, `dependencies_builder.py` (use-case block), `handler.py` (§8) and `domain/errors.py`. The SQL bodies of `session_credit_cards.sql` and `session_open_cases.sql` are copied into §6.2 and §6.3 with new headers.

From the sibling tools:
- `domain/value_objects/fraud_bands.py` (only `FRAUD_ABOVE` and `REVIEW_ABOVE`), from `transaction_fraud_detection`;
- `domain/value_objects/text_folding.py`, from `explain_transaction`.

---

## 10. Departures from §7.2, and product design doc fixes (`docs/LEDGERLENS_PRODUCT_DESIGN.md`, CRLF)

| §7.2 | This spec | Why |
|---|---|---|
| `FRAUD_SUSPECTED` on `fraud_score ≥ 0.7`, or a country not seen in 90 days | `Approved` and score above 50, over 30 days. The country part moves to `FOREIGN_TRANSACTION`. | The score is 0–100 (profiling). The user chose the 50/30 bands. A new country isn't fraud evidence in this data. |
| — | `UNRECOGNIZED_CHARGE_REVIEW` (30–50, weight 70) | The user chose two fraud reasons. |
| `DECLINED_TRANSACTION` on `status <> 'Approved'` | `Declined` only. `PENDING_TRANSACTION` and `REVERSED_TRANSACTION` are separate reasons (65). | Pending and reversed charges are different calls ("when will it post?", "where's my refund?"), as personas P02 and P03 show. |
| `TRANSACTION_DISPUTE` / `CARD_BLOCK_REQUEST` from dispute or block page visits | **Dropped.** | `digital_events` has no such pages (C1: 12 page titles confirmed). |
| — | `FAILED_APP_ACTION` (60), `CARD_NOT_ACTIVE` (60) | They come from signals that do exist: `event_type = 'Error'`, and `product_status`. |
| `FX_CLARIFICATION` (currency differs) | `FOREIGN_TRANSACTION`: the country **or** the currency differs | Covers the foreign charge in persona P05 (USD, in Brazil). |
| Decay of 1 point per hour on every reason | 1 per hour for 24 h and 72 h reasons, 1 per day for 30-day reasons, none for state reasons and cases | Hourly decay would floor a 30-day fraud charge within 57 hours. State reasons have no event time. |
| One SQL with `UNION ALL` signals and scoring | Four candidate queries, with rules and scoring in Python | Testable without a database. A failed source only loses its reasons. |
| Evidence as a formatted string | A structured object | The agent words it in the customer's language. Amounts stay exact. |

In the doc:
- Replace §7.2's taxonomy, output, query and tool_spec with this spec's.
- Add a line linking this spec.
- Keep CRLF.

---

## 11. Tests (`tests/unit/classify_call_type/`, pytest, TDD, no database or AWS)

| File | Covers |
|---|---|
| `test_call_reasons.py` | The enum order; each weight, window and decay from §3.1, pinned; `SOURCE_REASONS` covers every reason exactly once; `FRAUD_ABOVE == Decimal("50")` and `REVIEW_ABOVE == Decimal("30")` (pinned, the same as the fraud tool). |
| `test_reason_ranking.py` | Each reason's rule, with a positive and a negative case per condition: status, band edges (50.00 → review, 50.01 → fraud, 30.00 → nothing), window edges (exactly 72 h in, 72 h + 1 s out), Declined with a score of 62 → only `DECLINED`, `Closed` card → nothing, `Active` with `days_past_due` 0 or NULL → nothing, expiring at +30 days in and +31 out, folded "México"/"Mexico" not foreign, currency differs → foreign, NULL countries. Decay: hourly and daily values, the 40% floor, the future-event clamp, P07's 17.74 days → 0.77, half-up rounding. Best per reason, with tie-breaks. Ranking order and tie-breaks. Top 3. Empty input → `()`. |
| `test_classify_call_type_use_case.py` | Each query gets exactly the §4 params with naive UTC `as_of`; `review_above` is the constant. One source failing → its reasons in `unavailable` (enum order), and the rest ranked. A bad row → that source unavailable. All four failing → `DataSourceUnavailableError` when one was a connection error, else `CallReasonLookupError`. The 201-row cap logs and still ranks. Unknown customer → `reasons ()`. |
| `test_call_classification_presenter.py` | Evidence keys per reason exactly as in §5; amounts as 2-decimal strings; `confidence` as a number; `days_left`; **a recursive walk finds no key containing `fraud` or `score`**. |
| `test_classify_call_type_handler.py` | As for the sibling tools. |
| `test_query_contracts.py` | Placeholders match the params exactly in all 4 files; no stray `%`; no `SET`; columns selected; **`is_fraud` appears in no SQL file**; `fraud_score` only in `call_reason_transactions.sql`; `'Tarjeta Crédito'` (transactions, cards), `'Approved'` and `'Error'` NFC with no BOM; the transactions query filters `> %(review_above)s`; the windows `'30 days'`, `'72 hours'`, `'24 hours'`. `tool_spec.json` requires only `customer_id` and its description names all 11 reasons. |
| `test_delivery_wiring.py` + the copied infrastructure tests | As in the fraud spec. |

The whole suite passes in one session: `.venv/Scripts/python -m pytest tests/unit -q`.

---

## 12. Risks

| # | Risk | Handling |
|---|---|---|
| R1, R3, R5–R13 | Same as the other tools | Copied TODO tags. |
| K1 | **The weights are hand-set**, not learned (DEC-10). | They're pinned in tests and documented here. The ranking is a hypothesis list, and the tool description says so. |
| K2 | **The fraud bands are copied** from `transaction_fraud_detection`. | Both tools' tests pin `50` and `30`. |
| K3 | **The 72 h window misses older declines.** P05's code-14 decline is 80 h old. | That's the same window as `get_session_context`'s recent transactions, so the two tools agree. Widening it is a change to both. |
| K4 | **A past `AS_OF` shows current card and case states** (session context C3). | Accepted for demos. |
| K5 | **Not called automatically yet.** | A follow-up agent change (§1, out of scope). Until it ships, the tool description asks the model to call it at the start of the conversation. |
