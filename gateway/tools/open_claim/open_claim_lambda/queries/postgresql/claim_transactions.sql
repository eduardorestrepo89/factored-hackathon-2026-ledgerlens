-- claim_transactions (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The requested transactions that belong to the customer and were made with one
-- of their credit cards, with what OpenClaimUseCase needs to group and price the
-- claims. A requested id missing from the result isn't the customer's.
--
-- Parameters (psycopg named placeholders):
--   customer_id      text    required (the use case strips and uppercases it)
--   transaction_ids  text[]  required, 1 to 10 ids; psycopg sends the list as an array
--
-- transaction_id is the primary key, so there are no duplicate rows to remove.
-- The literal 'Tarjeta Crédito' is UTF-8; the connection uses client_encoding=utf8.
--
-- TODO(ledgerlens): W1 - = ANY(array) not yet run on a real Aurora DSQL cluster.
SELECT t.transaction_id,
       t.product_id,
       RIGHT(p.product_number, 4) AS card_last4,
       t.amount,
       t.currency,
       t.amount_usd
FROM transactions AS t
JOIN products AS p ON p.product_id = t.product_id
WHERE t.customer_id = %(customer_id)s
  AND t.transaction_id = ANY(%(transaction_ids)s)
  AND p.product_type = 'Tarjeta Crédito'
