-- list_card_transactions (PostgreSQL)
--
-- A customer's card transactions, newest first, one row per transaction_id.
-- Used by ListCardTransactionsUseCase.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text     required
--   date_from    date     required (the use case applies the 30-day default)
--   date_to      date     required
--   card_last4   text     optional, NULL means every card
--   merchant     text     optional, case-insensitive substring of merchant_name
--   min_amount   numeric  optional
--   max_amount   numeric  optional
--   status       text     optional
--   limit        integer  max rows plus one (the extra row sets truncated=true)
--
-- Optional parameters are cast so PostgreSQL knows their type even when NULL.
-- The merchant filter uses strpos() instead of ILIKE so wildcard characters in
-- the customer's text match literally.
--
-- TODO(ledgerlens): R3 - not yet run against a real PostgreSQL database. Column
--   names follow docs/LATAM_Bank_ERD.md; add integration tests with a container.
-- TODO(ledgerlens): R4 - transaction_status values (Approved, Declined, Pending)
--   are assumed; confirm them with the data dictionary.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
SELECT deduplicated.*
FROM (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id,
           t.transaction_date,
           RIGHT(p.product_number, 4) AS card_last4,
           t.merchant_name,
           t.merchant_category,
           t.amount,
           t.currency,
           t.channel,
           t.transaction_city,
           t.transaction_country,
           t.transaction_status
    FROM transactions AS t
    JOIN products AS p ON p.product_id = t.product_id
    WHERE t.customer_id = %(customer_id)s
      AND t.process_date BETWEEN %(date_from)s::date AND %(date_to)s::date
      AND (%(card_last4)s::text IS NULL
           OR RIGHT(p.product_number, 4) = %(card_last4)s::text)
      AND (%(merchant)s::text IS NULL
           OR strpos(lower(t.merchant_name), lower(%(merchant)s::text)) > 0)
      AND (%(min_amount)s::numeric IS NULL OR t.amount >= %(min_amount)s::numeric)
      AND (%(max_amount)s::numeric IS NULL OR t.amount <= %(max_amount)s::numeric)
      AND (%(status)s::text IS NULL OR t.transaction_status = %(status)s::text)
    ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
) AS deduplicated
ORDER BY deduplicated.transaction_date DESC NULLS LAST, deduplicated.transaction_id
LIMIT %(limit)s
