-- session_recent_transactions (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Credit-card transactions from the 72 hours up to as_of, newest first, with four
-- risk flags. Used by GetSessionContextUseCase; a failure here only makes the
-- recent_transactions section unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--   limit        integer    max rows plus one (the extra row marks the section truncated)
--
-- Credit cards only (product_type = 'Tarjeta Crédito'), so card_last4 always
-- matches a card in the cards section and the baseline compares like with like.
-- Flags (NULL means "not flagged"; the use case maps NULL to false):
--   is_declined            transaction_status = 'Declined'. Pending and Reversed
--                          are not declines; the model sees them in the status.
--   is_foreign             the transaction country differs from the customer's,
--                          ignoring case, outer spaces and Spanish accents (the
--                          data mixes Mexico and México).
--                          LEFT JOIN home keeps every row when the customer row is
--                          missing: the comparison is NULL, so not foreign.
--   is_above_usual_amount  above the 95th percentile of approved USD amounts in
--                          the 90 days before the window. With no history the
--                          baseline is Infinity, so nothing is flagged.
--   is_new_merchant        a merchant not seen in that history. A NULL merchant
--                          is never new.
-- process_date >= as_of::date - 90 is there for partition pruning (product design
-- section 8.1). CROSS JOIN baseline is safe: an aggregate always returns one row.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster.
--   percentile_cont ... WITHIN GROUP, DISTINCT ON inside a CTE and 'Infinity' for
--   numeric are standard PostgreSQL, but DSQL support is unverified. If DSQL
--   rejects one, this section comes back unavailable and the rest of the snapshot
--   still works. Column names follow docs/LATAM_Bank_ERD.md. The values
--   'Approved' and 'Declined' are confirmed in the dataset (risk C1, 2026-10-01).
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
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
       (lower(translate(btrim(r.transaction_country), 'ÁÉÍÓÚÜÑáéíóúüñ', 'AEIOUUNaeiouun'))
        <> lower(translate(btrim(h.country), 'ÁÉÍÓÚÜÑáéíóúüñ', 'AEIOUUNaeiouun'))) AS is_foreign,
       (r.amount_usd > COALESCE(b.p95_usd, 'Infinity'))          AS is_above_usual_amount,
       (r.merchant_name IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM hist AS x
                        WHERE x.merchant_name = r.merchant_name)) AS is_new_merchant
FROM recent AS r
LEFT JOIN home AS h ON TRUE
CROSS JOIN baseline AS b
ORDER BY r.transaction_date DESC NULLS LAST, r.transaction_id
LIMIT %(limit)s
