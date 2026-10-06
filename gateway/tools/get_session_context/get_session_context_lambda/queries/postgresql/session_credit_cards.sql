-- session_credit_cards (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The cards section of the session snapshot: the customer's credit cards in every
-- status, active first, one row per product_id. A copy of list_credit_cards.sql
-- from the list_credit_cards tool (copies, not shared code). Used by
-- GetSessionContextUseCase; a failure here only makes the cards section
-- unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text     required (the use case strips and uppercases it)
--   limit        integer  max rows plus one (the extra row sets truncated=true)
--
-- Credit cards are matched exactly on product_type = 'Tarjeta Crédito', a value
-- from the dataset. product_type is in Spanish, so a pattern on "card" would
-- match nothing. This file is UTF-8 and the connection uses client_encoding=utf8,
-- so the accent reaches the database intact.
-- available_credit is NULL when either operand is NULL, and negative when the
-- card is over its limit; both are returned as they are. product_id is selected
-- only for the deduplication and the final tie-break; the use case doesn't map it.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   RIGHT(), NULLS LAST and the binds are standard PostgreSQL, but DSQL support is
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster. The values 'Tarjeta Crédito' (product_type) and 'Active'
--   (product_status) are confirmed in the dataset (risk C1, 2026-10-01).
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time, keeping the latest last_updated. Drop it once the data
--   load deduplicates.
SELECT deduplicated.*
FROM (
    SELECT DISTINCT ON (p.product_id)
           p.product_id,
           RIGHT(p.product_number, 4)          AS card_last4,
           p.product_status,
           p.currency,
           p.current_balance,
           p.credit_limit,
           p.credit_limit - p.current_balance  AS available_credit,
           p.expiration_date,
           p.days_past_due
    FROM products AS p
    WHERE p.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
    ORDER BY p.product_id, p.last_updated DESC NULLS LAST
) AS deduplicated
ORDER BY (deduplicated.product_status = 'Active') DESC NULLS LAST,
         deduplicated.expiration_date DESC NULLS LAST,
         deduplicated.product_id
LIMIT %(limit)s
