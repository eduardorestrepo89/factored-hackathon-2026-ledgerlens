-- call_reason_transactions (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The charge candidates of ClassifyCallTypeUseCase: the customer's credit-card
-- charges of the last 72 hours, plus the approved ones of the last 30 days scored
-- above the review band. The SQL only narrows the candidates. Python applies every
-- reason rule, the windows included, so the rules have one owner. A failure here
-- only makes the transaction reasons unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id   text       required (the use case strips and uppercases it)
--   as_of         timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--   review_above  numeric    REVIEW_ABOVE from the domain (30)
--   limit         integer    the candidate cap plus one (201)
--
-- fraud_score is read for banding only. Python turns it into a reason and it never
-- leaves the Lambda. Credit cards are matched exactly on
-- product_type = 'Tarjeta Crédito', a value from the dataset. home_country is the
-- customer's latest country, for FOREIGN_TRANSACTION. process_date bounds the scan
-- to the partition days of the 30-day window. Newest first, so when the cap cuts,
-- the oldest charges are the ones dropped.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   RIGHT(), interval arithmetic and the binds are standard PostgreSQL, but DSQL
--   support is unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test
--   against a real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
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
