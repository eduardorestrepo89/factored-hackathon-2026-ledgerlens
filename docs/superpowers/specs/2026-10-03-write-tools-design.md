# Write tools (`block_credit_card`, `open_claim`, `human_agent_hand_off`): Design

**Date:** 2026-10-03
**Status:** Draft, for review.
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7.7–7.9, §10, §12
**Layout rules:** [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md). One folder per tool, wrapping every layer. Code is copied between tools, never shared.
**Copied from:** `gateway/tools/list_credit_cards/` (§8).

---

## 1. Goal

Build the three Gateway tool Lambdas that act for the customer in the fraud journey (J3):
- `block_credit_card` blocks one of the customer's credit cards.
- `open_claim` opens a fraud or dispute claim for some of the customer's card transactions, and returns the claim ID and the typical resolution time.
- `human_agent_hand_off` sends the conversation to a human agent with a summary.

`block_credit_card` and `open_claim` are the first tools that change data. They follow the read tools' hexagonal layers on Aurora DSQL, with a new database role. `human_agent_hand_off` publishes to SNS and never touches the database.

The three Lambdas are deployed by the data stack (`data-construct.ts`), as the read tools first were (their R1). **No Gateway target, Cedar rule or agent change is part of this work** (§10).

### Success criteria
- Each tool is a self-contained folder with the same layers as `list_credit_cards`. Nothing imports across tool folders.
- A write is safe to repeat. A retry after a lost connection, a DSQL conflict (`40001`) or a repeated model call never blocks twice or opens a second claim for the same transactions.
- Every failure reaches the agent as a fixed message, or a message built only from the tool's own validated input. Neither kind exposes internals.
- The write tools connect as `ll_write`. The read tools keep `ll_read`, with SELECT-only grants.
- `cdk deploy` of the data stack creates the three Lambdas, the write role and the SNS topic. One run of the new `access` stage creates `ll_write` and its grants without reloading data.
- Unit tests cover every layer with no database or AWS. `pytest tests/unit -q`, the CDK tests, `ruff format --check` and `ruff check` are clean.

### Decisions already made with the user
| Topic | Decision |
|---|---|
| Delivery | The Lambdas are deployed by `data-construct.ts` only. Gateway targets, Cedar statement 3 and the v2 prompt come later (§10). |
| Write strategy | Single autocommit statements made idempotent. The `DatabaseRepository.execute_query` port is unchanged. The write tools' copy of `DsqlRepository` retries `40001` and maps `23505`. |
| Confirmation | `customer_confirmed` is a boolean the model sets, as in the product design. The use case rejects anything but `true`. Server-side confirmation records stay a proposal. |
| Claims | One claim per card and currency. The claim ID is a hash of its content, so the same claim can't be opened twice. |
| Repeated actions | Blocking a blocked card or reopening an existing claim is a success, flagged `already_blocked` / `already_existed`, not an error. |
| Hand-off | SNS only. The Lambda runs outside the VPC and never touches DSQL. There's no `call_center_interactions` row: that table has no column for the summary. |
| Names | As in product design §7: `block_credit_card`, `open_claim`, `human_agent_hand_off`. |
| Demo data | No reset stage. Writes stay until the next full load. Smoke tests use a non-demo customer (§11). |

### Out of scope
- Gateway targets, Cedar policy changes, the v2 agent prompt (§10).
- Confirmation records, an audit table, card-processor APIs, the `call_center_interactions` row.
- The shared psycopg layer (v1 wiring spec §11).
- `classify_call_type`, `explain_transaction`, `transaction_fraud_detection`; frontend tool cards; the Tier-0 shell.

---

## 2. Layout

```
gateway/tools/block_credit_card/
├── tool_spec.json
├── requirements.txt                                 (copy)
└── block_credit_card_lambda/
    ├── domain/{entities/card_block.py, errors.py}
    ├── application/
    │   ├── ports/{database_repository,query_provider,errors}.py   (errors: + 2 classes, §6.1)
    │   └── use_cases/block_credit_card.py
    ├── infrastructure/{queries/file_query_provider.py, repositories/dsql_repository.py}
    ├── utils/connectors/{base,dsql}.py              (copy)
    ├── delivery/{handler.py, settings.py, dependencies/dependencies_builder.py, presenters/card_block.py}
    └── queries/postgresql/{find_credit_card,block_credit_card}.sql

gateway/tools/open_claim/
├── tool_spec.json
├── requirements.txt                                 (copy)
└── open_claim_lambda/
    ├── domain/{entities/claim.py, errors.py}
    ├── application/{ports/..., use_cases/open_claim.py}
    ├── infrastructure/..., utils/connectors/...     (same as block_credit_card)
    ├── delivery/{handler.py, settings.py, dependencies/dependencies_builder.py, presenters/claims.py}
    └── queries/postgresql/{claim_transactions,insert_claim,resolution_estimate}.sql

gateway/tools/human_agent_hand_off/                  (no requirements.txt: boto3 is in the runtime)
├── tool_spec.json
└── human_agent_hand_off_lambda/
    ├── domain/{entities/hand_off.py, errors.py}
    ├── application/{ports/{hand_off_publisher,errors}.py, use_cases/hand_off.py}
    ├── infrastructure/publishers/sns_publisher.py
    └── delivery/{handler.py, settings.py, dependencies/dependencies_builder.py, presenters/hand_off.py}

tests/unit/{block_credit_card,open_claim,human_agent_hand_off}/   ← packages, as tests/unit/list_credit_cards
```

| Tool | Handler string | Function name | Gateway target (later) |
|---|---|---|---|
| `block_credit_card` | `block_credit_card_lambda/delivery/handler.handler` | `ledgerlens-block-credit-card` | `block-credit-card-target` |
| `open_claim` | `open_claim_lambda/delivery/handler.handler` | `ledgerlens-open-claim` | `open-claim-target` |
| `human_agent_hand_off` | `human_agent_hand_off_lambda/delivery/handler.handler` | `ledgerlens-human-agent-hand-off` | `human-agent-hand-off-target` |

Every handler keeps the read tools' shape:
- the `<target>___<tool>` tool-name guard
- the graph built once at module load (`None` on bad configuration → the unavailable message)
- `DomainError` → `{"error": message}`; any other exception → a fixed generic message
- success → `{"content": [{"type": "text", "text": <JSON>}]}`
- an `R1` TODO saying no Gateway target points at the tool yet

---

## 3. `block_credit_card`

### 3.1 Input (`tool_spec.json`)

```json
[
  {
    "name": "block_credit_card",
    "description": "Blocks one of the customer's credit cards immediately so it can't be charged again. Only call after the customer explicitly said yes, in this conversation, to blocking the card with these last 4 digits. Can't be undone through this assistant. Returns JSON with 'card_last4', 'status' and 'already_blocked' (true when the card was already blocked; that is not an error).",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's id from get_session_context." },
        "card_last4": { "type": "string", "description": "Last 4 digits of the card, from list_credit_cards." },
        "reason": { "type": "string", "enum": ["suspected_fraud", "lost", "stolen", "customer_request"] },
        "customer_confirmed": { "type": "boolean", "description": "Must be true: the customer explicitly said yes to blocking this card." }
      },
      "required": ["customer_id", "card_last4", "reason", "customer_confirmed"]
    }
  }
]
```

The handler passes each event value bare (`None` when missing or when the event isn't an object). The use case cleans them before touching the database:
- `customer_id`: as in `list_credit_cards` (strip, uppercase, non-empty string).
- `card_last4`: a string; stripped; exactly 4 ASCII digits.
- `reason`: a string; stripped and lowercased; one of the four enum values.
- `customer_confirmed`: must be exactly `True`. Anything else (missing, `false`, `"true"`) raises `InvalidInputError("customer_confirmed", "must be true: ask the customer to confirm the block first")`.

### 3.2 Use case (`BlockCreditCardUseCase`)

`execute(customer_id, card_last4, reason, customer_confirmed, now)`. `now` is the handler's `CLOCK.now()` (AS_OF in demos), so the block lines up with the clock the read tools use.

1. Run `find_credit_card` with `{customer_id, card_last4}`.
   - No row → `CardNotFoundError(card_last4)`.
   - Two rows → `AmbiguousCardError(card_last4)`.
   - `Closed` → `CardClosedError(card_last4)`.
   - `Blocked` → return `CardBlock(card_last4, status="Blocked", already_blocked=True)` without writing.
2. Run `block_credit_card` with `{customer_id, product_id, last_updated}`. `last_updated` is `now` as naive UTC (the column is `timestamp`).
   - One row → `CardBlock(card_last4, "Blocked", already_blocked=False)`.
   - No row: the status changed between the two statements, or a retry after a lost connection had already committed. Run `find_credit_card` once more and decide from it, as in step 1. Still not `Blocked`/`Closed` → `CardUpdateError`.
3. Log one audit line: `customer_id`, `card_last4`, `reason`, `already_blocked`. `reason` has no column in `products`, so the log is its only record.

Port errors map as in §6.2. Rows that can't be mapped → `CardDataIntegrityError`.

### 3.3 SQL

`find_credit_card.sql`:
```sql
SELECT p.product_id, p.product_status
FROM products AS p
WHERE p.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND RIGHT(p.product_number, 4) = %(card_last4)s
ORDER BY p.product_id
LIMIT 2
```

`block_credit_card.sql`:
```sql
UPDATE products
SET product_status = 'Blocked',
    last_updated   = %(last_updated)s
WHERE product_id = %(product_id)s
  AND customer_id = %(customer_id)s
  AND product_status NOT IN ('Blocked', 'Closed')
RETURNING product_id
```
- `LIMIT 2` is enough to tell one card from an ambiguous match.
- `product_id` is the table's primary key, so there's no `DISTINCT ON`. R8 doesn't apply to these new queries.
- The guard in the `WHERE` makes the `UPDATE` safe to run twice. `customer_id` is repeated as a second guard.
- `RETURNING` lets the unchanged port (`execute_query` → `fetchall`) run the `UPDATE`.

### 3.4 Output (`presenters/card_block.py`)

```json
{ "card_last4": "4821", "status": "Blocked", "already_blocked": false }
```

### 3.5 Domain errors

| Cause | Error | Message |
|---|---|---|
| Bad input | `InvalidInputError` | Copied template: "Invalid value for '<field>': <reason>. Ask the customer to confirm and retry." |
| No card | `CardNotFoundError` | "No credit card ending in {last4} was found for this customer. Check the card with list_credit_cards and confirm it with the customer." |
| Two cards | `AmbiguousCardError` | "More than one of the customer's credit cards ends in {last4}, so it can't be blocked here. Don't retry; offer an urgent hand-off to a human agent." |
| Closed | `CardClosedError` | "The card ending in {last4} is closed, so it can't be charged and needs no block. Tell the customer." |
| Connection or conflict | `DataSourceUnavailableError` | "The card service is temporarily unavailable. Tell the customer and offer to retry in a moment or hand off to a human agent." |
| Other data access | `CardUpdateError` | "The card couldn't be blocked due to an internal error. Don't retry; offer an urgent hand-off to a human agent." |
| Bad row | `CardDataIntegrityError` | "Card data came back in an unexpected format. Don't retry; offer an urgent hand-off to a human agent." |

`{last4}` is the cleaned 4-digit input, so these messages carry nothing from the database.

---

## 4. `open_claim`

### 4.1 Input (`tool_spec.json`)

```json
[
  {
    "name": "open_claim",
    "description": "Opens a fraud or dispute claim for one or more of the customer's credit card transactions. Only call after the customer confirmed, in this conversation, exactly which transactions they don't recognise or dispute. Opens one claim per card and currency. Returns JSON with 'claims' (claim_id, card_last4, transaction_ids, claimed_amount, currency, priority, status, already_existed) and 'resolution_estimate' (median_days and p90_days from similar past claims, or null when there is not enough history). Never promise a refund or an outcome.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's id from get_session_context." },
        "transaction_ids": { "type": "array", "items": { "type": "string" }, "minItems": 1, "maxItems": 10, "description": "Transaction ids from list_card_transactions." },
        "claim_type": { "type": "string", "enum": ["fraud", "dispute"], "description": "fraud: the customer doesn't recognise the charges. dispute: they recognise them but contest them." },
        "customer_statement": { "type": "string", "description": "What the customer said happened, in their words, at most 500 characters." },
        "customer_confirmed": { "type": "boolean", "description": "Must be true: the customer explicitly confirmed these transactions." }
      },
      "required": ["customer_id", "transaction_ids", "claim_type", "customer_statement", "customer_confirmed"]
    }
  }
]
```

Input cleaning in the use case:
- `customer_id`, `customer_confirmed`: as in §3.1.
- `transaction_ids`: a list of 1 to 10 strings. Each is stripped and uppercased, non-empty and at most 30 characters (`varchar(30)`). Duplicates are dropped, keeping the first occurrence.
- `claim_type`: stripped, lowercased, `fraud` or `dispute`.
- `customer_statement`: a string, stripped, 1 to 500 characters.

### 4.2 Use case (`OpenClaimUseCase`)

`execute(customer_id, transaction_ids, claim_type, customer_statement, customer_confirmed, now)`.

1. Run `claim_transactions` with `{customer_id, transaction_ids}`. Any requested ID missing from the rows → `TransactionsNotFoundError(missing_ids)`. That covers IDs that don't exist, belong to someone else or aren't on a credit card.
2. Group the rows by `(product_id, currency)`. Order the groups by `card_last4`, then `currency`, so the output is deterministic.
3. For each group, build a `Claim`:
   - `claim_id = "CMP-" + base32(sha256("|".join([customer_id, claim_type, product_id, currency, ",".join(sorted(ids))])))[:20]`. That gives 24 characters, which matches the dataset's `CMP-` + 20 format.
   - `claimed_amount = sum(amount)`.
   - `priority = "High"` when any `amount_usd` is NULL or their sum is above 500, else `"Medium"`. The 500 matches the fraud protocol's hand-off threshold.
   - `subcategory`: `"Cargo no reconocido"` for fraud, `"Cobro indebido"` for a dispute. Both are values in the dataset.
   - `description = customer_statement + " | tx: " + ",".join(ids)`.
4. Run `insert_claim` once per group. A `DuplicateKeyError` (SQLSTATE `23505`) means this exact claim exists already, from a retry or a repeated call. The claim is then returned with `already_existed=True`, without a second write.
5. Run `resolution_estimate` with `{subcategory, since}`, where `since = now - 365 days`.
   - No row (fewer than 20 cases) → `None`.
   - **Any error here is logged and gives `None`.** The claims are already written, so the call must not report a failure.
   - Each value is rounded up to whole days.

Port errors in steps 1 and 4 map as in §6.2. With several groups, an error in a later group leaves the earlier claims written. A retry returns those as `already_existed` and opens the rest (risk W5).

### 4.3 SQL

`claim_transactions.sql`:
```sql
SELECT t.transaction_id, t.product_id, RIGHT(p.product_number, 4) AS card_last4,
       t.amount, t.currency, t.amount_usd
FROM transactions AS t
JOIN products AS p ON p.product_id = t.product_id
WHERE t.customer_id = %(customer_id)s
  AND t.transaction_id = ANY(%(transaction_ids)s)
  AND p.product_type = 'Tarjeta Crédito'
```
`transaction_id` is the primary key, so there's no `DISTINCT ON`. psycopg sends the Python list as an array.

`insert_claim.sql`:
```sql
INSERT INTO complaints (
    complaint_id, creation_date, process_date, customer_id, case_type, category,
    subcategory, reception_channel, affected_product_id, description,
    claimed_amount, currency, priority, status, sla_breached, is_repeat_complainer
) VALUES (
    %(complaint_id)s, %(creation_date)s, %(process_date)s, %(customer_id)s, 'Claim', 'Transactions',
    %(subcategory)s, 'Web', %(product_id)s, %(description)s,
    %(claimed_amount)s, %(currency)s, %(priority)s, 'Open', false, false
)
RETURNING complaint_id
```
- These values pass the schema's CHECK constraints. **The product design's `'Cards'` and `'AI Assistant'` don't** (§9).
- `creation_date` is `now` as naive UTC. `process_date` is its date.
- `is_repeat_complainer` is `false`. Computing it needs a query the demo doesn't need.

`resolution_estimate.sql`:
```sql
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_days) AS median_days,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_days) AS p90_days
FROM complaints
WHERE case_type = 'Claim'
  AND category = 'Transactions'
  AND subcategory = %(subcategory)s
  AND resolution_days IS NOT NULL
  AND creation_date >= %(since)s
HAVING COUNT(*) >= 20
```
`compensation_granted` is never read, because quoting it would sound like a promise.

### 4.4 Output (`presenters/claims.py`)

```json
{
  "claims": [
    {
      "claim_id": "CMP-4KQ2ZJ7M3XH5TB6RWN2Y",
      "card_last4": "4821",
      "transaction_ids": ["TRX-88", "TRX-89"],
      "claimed_amount": "835.00",
      "currency": "USD",
      "priority": "High",
      "status": "Open",
      "already_existed": false
    }
  ],
  "resolution_estimate": { "median_days": 5, "p90_days": 12 }
}
```

### 4.5 Domain errors

| Cause | Error | Message |
|---|---|---|
| Bad input | `InvalidInputError` | Copied template |
| Missing IDs | `TransactionsNotFoundError` | "These transactions weren't found among the customer's credit card transactions: {ids}. Check them with list_card_transactions and retry." |
| Connection or conflict | `DataSourceUnavailableError` | "The claim service is temporarily unavailable. Tell the customer and offer to retry in a moment or hand off to a human agent." |
| Other data access | `ClaimError` | "The claim couldn't be opened due to an internal error. Don't retry; offer a hand-off to a human agent." |
| Bad row | `ClaimDataIntegrityError` | "Transaction data came back in an unexpected format. Don't retry; offer a hand-off to a human agent." |

`{ids}` are the cleaned input IDs, never database text.

---

## 5. `human_agent_hand_off`

> **Superseded:** the SNS publisher, topic and settings in this section were removed by [2026-10-03-human-hand-off-frontend-design.md](2026-10-03-human-hand-off-frontend-design.md). The input schema and validation still hold.

### 5.1 Input (`tool_spec.json`)

```json
[
  {
    "name": "human_agent_hand_off",
    "description": "Sends the conversation to a human agent. Use when the customer asks for a person, after a confirmed fraud case, for anything out of scope, or when you can't resolve the request. The summary must let the agent continue without asking the customer anything again: the card's last 4 digits, the transactions, what was blocked or opened (with ids) and what the customer said. Returns JSON with 'hand_off_id', 'status' and 'priority'. Don't promise a time.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's id from get_session_context." },
        "priority": { "type": "string", "enum": ["high", "normal"] },
        "reason": { "type": "string", "enum": ["FRAUD_CONFIRMED", "CUSTOMER_REQUEST", "UNRESOLVED", "OUT_OF_SCOPE"] },
        "summary": { "type": "string", "description": "Complete summary for the human agent, at most 2000 characters." },
        "related_ids": { "type": "array", "items": { "type": "string" }, "maxItems": 20, "description": "Ids of the transactions, claims and other records involved." }
      },
      "required": ["customer_id", "priority", "reason", "summary"]
    }
  }
]
```

Input cleaning: `customer_id` as in §3.1. `priority` is stripped and lowercased; `reason` stripped and uppercased; both must be enum values. `summary` is stripped, 1 to 2,000 characters. `related_ids` is optional (missing → empty): a list of at most 20 strings, each stripped, uppercased and matching `[A-Z0-9-]{1,40}`.

### 5.2 Layers

- **Entity:** `HandOff(customer_id, priority, reason, summary, related_ids)`.
- **Port:** `HandOffPublisher.publish(hand_off) -> str` returns a reference for the hand-off. It raises the port error `PublishError`.
- **Adapter:** `SnsHandOffPublisher(topic_arn, region, sns_client=None)` creates the boto3 client lazily, as `DsqlConnector` does. It calls `publish` with:
  - `Message`: the entity as JSON plus `"source": "ledgerlens"`. SNS adds its own timestamp.
  - `Subject`: `"[HIGH] LedgerLens hand-off: FRAUD_CONFIRMED"`, ASCII and at most 100 characters.
  - `MessageAttributes`: `priority` and `reason`, so a queue subscriber can filter later.
  - It returns SNS's `MessageId`. `botocore` `ClientError`/`BotoCoreError` → `PublishError`.
- **Use case:** `HandOffUseCase(publisher).execute(customer_id, priority, reason, summary, related_ids)` validates, publishes and returns `HandOffResult(hand_off_id, priority)`. `PublishError` → `HandOffUnavailableError`.
- **Settings:** `HANDOFF_TOPIC_ARN` (required, must start with `arn:aws:sns:`), `AWS_REGION`. There's no clock and no database settings.

### 5.3 Output and errors

```json
{ "hand_off_id": "<SNS MessageId>", "status": "queued", "priority": "high" }
```

| Cause | Error | Message |
|---|---|---|
| Bad input | `InvalidInputError` | Copied template |
| SNS failed | `HandOffUnavailableError` | "The hand-off to a human agent couldn't be sent right now. Tell the customer you couldn't reach a person and that they can contact the bank through its usual channels." |

---

## 6. Shared changes in the two write tools (copied, not shared)

### 6.1 Port errors

`application/ports/errors.py` is copied and gains two classes, both subclasses of `DataAccessError`:
- `DuplicateKeyError`: the statement broke a unique constraint.
- `WriteConflictError`: DSQL kept rejecting the write with a concurrency conflict.

### 6.2 Port → domain mapping (both write tools)

| Port error | Domain error |
|---|---|
| `DataSourceConnectionError`, `WriteConflictError` | `DataSourceUnavailableError` (retrying later may work) |
| `DuplicateKeyError` | Handled by `open_claim` (§4.2). Anywhere else, the tool's internal error. |
| Any other `DataAccessError` | `CardUpdateError` / `ClaimError` |

### 6.3 `DsqlRepository` (write copy)

This is the read copy with two rules added before its existing `except` clauses:
- **SQLSTATE `40001`** (DSQL's optimistic-concurrency conflict, which psycopg reports as an `OperationalError`) is retried up to **3 attempts in all**, after a jittered sleep of 50–150 ms × attempt. The connection is kept, because nothing is wrong with it. After the last attempt → `WriteConflictError`. The sleep is injected so tests don't wait.
- **SQLSTATE `23505`** → `DuplicateKeyError`, never retried.

The existing reset-and-retry-once after a lost connection stays as it is. For writes it's safe only because every write in §3.3 and §4.3 is idempotent. The module docstring says so, and replaces the read copy's "SELECT-only" note and its R6 TODO.

### 6.4 Settings

`settings.py` is copied with two changes:
- `DEFAULT_DSQL_DB_USER = "ll_write"`, so a missing variable can't connect a write tool as the read role.
- `DatabaseSettings` drops `max_rows` and `MAX_ROWS`: no write tool returns a list.

`ClockSettings` (AS_OF) is kept and passed to `execute` as `now`, as `list_card_transactions` passes `today`.

---

## 7. Database access

### 7.1 `data_load/schema.sql`

```sql
-- The write tools' role (block_credit_card, open_claim). Created if missing; mapped to
-- the ledgerlens-write-tools IAM role by the load and access stages.
CREATE ROLE ll_write WITH LOGIN;
GRANT SELECT ON products, transactions, complaints TO ll_write;
GRANT UPDATE ON products TO ll_write;
GRANT INSERT ON complaints TO ll_write;
```
`ddl.py` already collects `CREATE ROLE … WITH LOGIN` and `GRANT` statements, so it needs no change.

### 7.2 `data_load/dsql.py` and `__main__.py`

- `apply_schema(conn, plan, role_arns)` takes `{"ll_read": <tools role ARN>, "ll_write": <write tools role ARN>}`. It recreates the tables, then calls the new `apply_access`.
- `apply_access(conn, plan, role_arns)` does the second half of today's `apply_schema`, for every role:
  1. Check that every role in the plan has a valid IAM role ARN. Fail before any statement runs if one is missing.
  2. Create missing roles.
  3. Add missing `AWS IAM GRANT <role> TO '<arn>'` mappings.
  4. Re-run the grants.
- **`load`** reads `WRITE_TOOLS_ROLE_ARN` as well as `TOOLS_ROLE_ARN`.
- **New `access` stage:** `python -m data_load access` needs `DSQL_ENDPOINT`, `TOOLS_ROLE_ARN` and `WRITE_TOOLS_ROLE_ARN`. It runs `apply_access` only, with no table changes, so `ll_write` can be added to a loaded cluster.
- **How to run it:** a CodeBuild run of the pipeline project with `STAGE=access`, because the cluster policy only admits the loader from outside the VPC.

---

## 8. CDK (`infra-cdk/lib/data-construct.ts` only)

- **`WriteToolsRole`:**
  - `roleName: "ledgerlens-write-tools"`, assumed by Lambda.
  - `AWSLambdaVPCAccessExecutionRole`, plus `dsql:DbConnect` on the cluster (never `DbConnectAdmin`).
  - Exposed as `writeToolsRole`. Its ARN goes into the CodeBuild environment as `WRITE_TOOLS_ROLE_ARN`.
- **The tools loop** gets an optional `role` per entry (default `this.toolsRole`):
  ```ts
  { tool: "block_credit_card", id: "BlockCreditCard", role: writeToolsRole },
  { tool: "open_claim", id: "OpenClaim", role: writeToolsRole },
  ```
  The existing entries and their construct ids don't change, so the deployed read tools aren't replaced.
- **`HumanHandOffTopic`:**
  - `sns.Topic`, `topicName: "ledgerlens-human-handoff"`, encrypted with the AWS-managed key `alias/aws/sns`.
  - When `config.admin_user_email` is set, an `EmailSubscription` to it. The recipient confirms it once from the email.
- **`HumanAgentHandOffFn`:**
  - `PythonFunction`, `functionName: "ledgerlens-human-agent-hand-off"`, Python 3.13 on ARM64, the same bundling excludes.
  - **No VPC.** Its own role, which only gets `topic.grantPublish(fn)`.
  - Timeout 10 s, `HANDOFF_TOPIC_ARN` in the environment, a one-week log group.
- The SNS endpoint isn't added to the VPC: the hand-off Lambda is the only thing that publishes, and it runs outside the VPC.

---

## 9. Product design updates

- **§7.7, §7.8 and §7.9:** each gets "Spec: [2026-10-03-write-tools-design.md](superpowers/specs/2026-10-03-write-tools-design.md)."
- **§7.8:**
  - The `INSERT` uses `category 'Transactions'`, subcategory `'Cargo no reconocido'`/`'Cobro indebido'` and `reception_channel 'Web'`. The old values fail the schema's CHECK constraints.
  - The resolution query uses the same category and subcategories.
  - One claim per card and currency.
- **§7.9:** SNS only. The `call_center_interactions` row is dropped, because the table has no column for the summary.
- **§15:**
  - The SNS topic item is ticked.
  - The Lambda IAM item is updated: a separate write role; SNS publish only on the hand-off role.

---

## 10. Deferred: wiring into the agent

The Gateway work is left for later. When it's done, it must do all of these:
1. **Gateway targets:** add three entries to `toolTargets` in `backend-construct.ts`, imported by name like the read tools.
2. **Cedar:**
   - Add the three actions to statements 1 and 2.
   - Add statement 3: `forbid` block and open-claim `when { !(context.input has customer_confirmed) || context.input.customer_confirmed != true }`.
   - The `has` guard matters. A missing argument would otherwise make the `forbid` fail to evaluate, and Cedar skips a `forbid` that fails, so the call would be allowed.
3. **Prompt v2:**
   - Replace "FRAUD AND ACTIONS" with product design §9 part 3 (protect, scope, claim, hand off).
   - Make BOUNDARIES offer `human_agent_hand_off`.
   - After a hand-off, the agent says a person has the case and the summary.
   - Bump `PROMPT_VERSION` to `"v2"`.

   Until then the deployed agent keeps v1, which tells the customer it can only read. A v2 prompt without the Gateway targets would offer actions the agent can't take.
4. **Remove the tools' R1 TODOs.**

---

## 11. Rollout

This happens only after the branch's code review. The user starts each deploy.
1. `cdk deploy` the data stack. It creates the write role, the three Lambdas and the topic.
2. Start the pipeline's CodeBuild project once with `STAGE=access`. Check the log for `AWS IAM GRANT ll_write`.
3. Smoke test each Lambda by direct invoke. Pass client context `{"custom": {"bedrockAgentCoreToolName": "x___<tool>"}}`. Use a **non-demo customer**, so P03's card stays `Active` for the demo:
   - `block_credit_card` with `customer_confirmed: false` → the `customer_confirmed` error. With `true` → `already_blocked: false`. Again → `already_blocked: true`.
   - `open_claim` twice with the same input → the same `claim_id`, the second time `already_existed: true`. Check `resolution_estimate`: `null` on both runs suggests `percentile_cont` failed on DSQL (W1). The log says which.
   - `human_agent_hand_off` → a `hand_off_id`, and the email arrives once the subscription is confirmed.
4. Writes stay until the next full load (W3).

---

## 12. Tests

All pytest, TDD, no database or AWS. Each tool's folder copies `conftest.py` and `fakes.py` from `tests/unit/list_credit_cards/` and adapts them.

| Area | Covers |
|---|---|
| Use cases | Every input rule, including `customer_confirmed` = `false`, `"true"` or missing. Block: the four outcomes of step 1, the 0-row update and its re-read. Claim: missing IDs, grouping and its order, the claim-ID hash (stable, independent of input order, 24 characters), priority with a NULL `amount_usd`, `DuplicateKeyError` → `already_existed`, the estimate's `None`/rounding/error-swallowing. Hand-off: the fields, `PublishError`. Each port error → its domain error. |
| Handlers | Success format, bare values passed through, a non-object event, domain error, unexpected error, wrong tool name, missing configuration, `now` from `CLOCK` |
| Presenters | The JSON shapes in §3.4, §4.4 and §5.3; amounts as 2-decimal strings |
| `DsqlRepository` (write copies) | `40001` retried with no reset and then `WriteConflictError`; `23505` → `DuplicateKeyError` with no retry; the copied read behavior unchanged |
| `SnsHandOffPublisher` | The publish arguments (subject, attributes, JSON), `MessageId` returned, client errors → `PublishError`, lazy client |
| Query contracts | Placeholders match params both ways; the exact Spanish literals in UTF-8; the CHECK-constrained values; `tool_spec.json` names and required fields |
| Settings and wiring | `ll_write` default; no `MAX_ROWS`; `HANDOFF_TOPIC_ARN` required and validated; bad configuration → `None` |
| `data_load` | `apply_access` maps both roles, fails before any statement when an ARN is missing, re-runs grants; the `access` CLI stage; `load` passes both ARNs; the schema plan has `ll_write` and its grants |
| `test_tool_requirements.py` | Adds `block_credit_card` and `open_claim` |
| `data-construct.test.ts` | The write role and its single DSQL action; the two write Lambdas on it, in the VPC; the topic, encrypted; the hand-off Lambda outside the VPC with publish rights only; `WRITE_TOOLS_ROLE_ARN` in CodeBuild; the read tools' construct ids unchanged |

---

## 13. Risks

| # | Risk | Handling |
|---|---|---|
| W1 | `= ANY(array)`, `percentile_cont`, and `UPDATE`/`INSERT … RETURNING` haven't been run on DSQL | The smoke test (§11). The estimate fails safe to `null`. |
| W2 | `customer_confirmed` is set by the model, so it proves intent only as far as the model is honest | The use case rejects anything but `true`. Cedar statement 3 comes with the Gateway (§10). Confirmation records stay the research report's proposal. |
| W3 | Writes change the demo data until the next full load | The smoke test uses a non-demo customer. Reload before the final demo if a rehearsal touches P03. |
| W4 | The same transactions, type, card and currency always give the same claim ID, even after that claim is resolved | Acceptable for the demo. A real system would key on an open-claim lookup. |
| W5 | A multi-group claim can fail after some groups were written | A retry is idempotent and finishes the rest. |
| W6 | Until the Gateway lands, the tools are reachable only by direct invoke | IAM allows only the deployer. The R1 TODO in each handler. |
| W7 | The hand-off summary goes by plain email to `admin_user_email` | Demo only. A contact-center queue replaces email later (Q5). |
| W8 | The block `reason` is kept only in CloudWatch Logs | No audit table yet (product design §14). |
| S4 | The copies drift | The copy list is §2 plus §6. A change to a copied file names every copy. |
