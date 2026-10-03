-- fraud_card_exists (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Does one of the customer's credit cards end in card_last4? Used by
-- TransactionFraudDetectionUseCase before a sweep, so a mistyped last 4 gives
-- "card not found" instead of looking like a clean card.
--
-- A card in any status counts: a blocked card's charges can still be fraud.
-- Credit cards only, matched exactly on product_type = 'Tarjeta Crédito'.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text  required
--   card_last4   text  required, 4 ASCII digits
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster.
--   Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
SELECT 1 AS card_exists
FROM products AS p
WHERE p.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND RIGHT(p.product_number, 4) = %(card_last4)s
LIMIT 1
