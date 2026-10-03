-- find_credit_card (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The customer's credit cards whose number ends in the given 4 digits, with their
-- status. Used by BlockCreditCardUseCase before the UPDATE: no row means no such
-- card, and two rows mean the digits are ambiguous (LIMIT 2 is enough to tell).
--
-- Parameters (psycopg named placeholders):
--   customer_id  text  required (the use case strips and uppercases it)
--   card_last4   text  required, exactly 4 digits
--
-- product_id is the primary key, so there are no duplicate rows to remove. The
-- literal 'Tarjeta Crédito' is UTF-8; the connection uses client_encoding=utf8.
--
-- TODO(ledgerlens): W1 - not yet run against a real Aurora DSQL cluster.
SELECT p.product_id,
       p.product_status
FROM products AS p
WHERE p.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND RIGHT(p.product_number, 4) = %(card_last4)s
ORDER BY p.product_id
LIMIT 2
