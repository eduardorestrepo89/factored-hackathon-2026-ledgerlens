-- fraud_card_sweep (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Every charge on one of the customer's credit cards in the 30 days up to as_of,
-- one row per transaction_id. Returns the flagged ones (score above
-- review_above), highest score first, each with checked = how many charges the
-- window holds, scored or not. Used by TransactionFraudDetectionUseCase in card
-- mode.
--
-- totals always has one row, and the LEFT JOIN keeps it when nothing is
-- flagged: a clean card then returns one count-only row (NULL transaction
-- columns, real checked) instead of no row. The outer ORDER BY repeats the
-- flagged order, because a join doesn't keep a CTE's order. LIMIT cuts only
-- the flagged set.
--
-- The window filters on transaction_date, lower bound inclusive. process_date is
-- there only for partition pruning (product design section 8.1); its extra day
-- covers charges processed a day later. A card with two products ending in the
-- same 4 digits (one replaced, say) is swept across both: the customer sees one
-- last 4. Credit cards only, matched exactly on product_type = 'Tarjeta Crédito'.
--
-- DEC-10: the outcome label column is never read. The verdict comes from
-- fraud_score alone, banded in Python; the score never leaves the Lambda.
--
-- Parameters (psycopg named placeholders):
--   customer_id   text       required
--   card_last4    text       required, 4 ASCII digits
--   as_of         timestamp  required, naive UTC
--   review_above  numeric    required, the domain's REVIEW_ABOVE (30)
--   limit         integer    max flagged rows plus one (the extra row sets truncated)
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   CTEs, LEFT JOIN ... ON TRUE, NULLS LAST and the binds are standard PostgreSQL,
--   but DSQL support and the plan under the 128 MiB per-query limit are
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
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
