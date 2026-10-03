-- block_credit_card (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Blocks the one card find_credit_card returned. Used by BlockCreditCardUseCase.
--
-- Parameters (psycopg named placeholders):
--   product_id    text       required, from find_credit_card
--   customer_id   text       required, a second guard on the card's owner
--   last_updated  timestamp  required, the tool's "now" (AS_OF in demos), naive UTC
--
-- The status guard makes the statement safe to run twice: a card that is
-- already blocked, or closed, isn't touched and no row comes back. RETURNING
-- lets the repository read the result of an UPDATE with fetchall().
--
-- TODO(ledgerlens): W1 - UPDATE ... RETURNING not yet run on a real Aurora DSQL cluster.
UPDATE products
SET product_status = 'Blocked',
    last_updated   = %(last_updated)s
WHERE product_id = %(product_id)s
  AND customer_id = %(customer_id)s
  AND product_status NOT IN ('Blocked', 'Closed')
RETURNING product_id
