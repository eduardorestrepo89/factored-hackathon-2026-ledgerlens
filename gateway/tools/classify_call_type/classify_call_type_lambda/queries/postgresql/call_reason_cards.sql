-- call_reason_cards (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The card candidates of ClassifyCallTypeUseCase: the customer's credit cards in
-- every status, one row per product_id at its latest state. Python decides
-- CARD_NOT_ACTIVE, PAYMENT_OVERDUE and CARD_EXPIRING. A failure here only makes
-- the card reasons unavailable. There is no row cap: a customer has a handful of
-- cards. The deduplication is the one in get_session_context's
-- session_credit_cards.sql (copies, not shared code).
--
-- Parameters (psycopg named placeholders):
--   customer_id  text  required (the use case strips and uppercases it)
--
-- Credit cards are matched exactly on product_type = 'Tarjeta Crédito', a value
-- from the dataset. product_id is selected only for the deduplication and the
-- final tie-break; the use case doesn't map it. product_status is today's state,
-- even on a past AS_OF (risk K4, accepted for demos).
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   RIGHT(), NULLS LAST and the binds are standard PostgreSQL, but DSQL support is
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time, keeping the latest last_updated. Drop it once the data
--   load deduplicates.
SELECT deduplicated.card_last4,
       deduplicated.product_status,
       deduplicated.expiration_date,
       deduplicated.days_past_due
FROM (
    SELECT DISTINCT ON (p.product_id)
           p.product_id,
           RIGHT(p.product_number, 4)  AS card_last4,
           p.product_status,
           p.expiration_date,
           p.days_past_due
    FROM products AS p
    WHERE p.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
    ORDER BY p.product_id, p.last_updated DESC NULLS LAST
) AS deduplicated
ORDER BY deduplicated.card_last4, deduplicated.product_id
