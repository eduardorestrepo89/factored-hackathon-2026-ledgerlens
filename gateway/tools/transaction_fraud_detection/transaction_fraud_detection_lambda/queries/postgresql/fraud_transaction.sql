-- fraud_transaction (PostgreSQL dialect, runs on Aurora DSQL)
--
-- One credit-card charge of the customer, with the fraud engine's stored score.
-- Used by TransactionFraudDetectionUseCase in transaction mode.
--
-- customer_id in the WHERE is the ownership check: another customer's charge,
-- or a charge on a non-credit product, returns no row ("not found"). Credit
-- cards only, matched exactly on product_type = 'Tarjeta Crédito' (the dataset's
-- Spanish value), the filter every tool uses. transaction_date <= as_of keeps
-- the demo's "now" honest.
--
-- DEC-10: the outcome label column is never read. The verdict comes from
-- fraud_score alone, banded in Python; the score never leaves the Lambda.
--
-- Parameters (psycopg named placeholders):
--   customer_id     text       required
--   transaction_id  text       required
--   as_of           timestamp  required, naive UTC
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   NULLS LAST and the binds are standard PostgreSQL, but DSQL support is
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
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
