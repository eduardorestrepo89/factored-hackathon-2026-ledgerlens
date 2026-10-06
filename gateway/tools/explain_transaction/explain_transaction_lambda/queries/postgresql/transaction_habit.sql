-- transaction_habit (PostgreSQL dialect, runs on Aurora DSQL)
--
-- How a charge compares with its card's approved charges of the 90 days before
-- it: how many there were, how many at the same merchant, the usual amount range
-- in the charge's currency, and whether the charge's country was seen before.
-- Used by ExplainTransactionUseCase for the habit section.
--
-- customer_id and product_id come from the core query, which already checked
-- ownership and the credit-card filter. The charge itself is excluded. The
-- range is the 10th to 90th percentile of amounts in the same currency; Python
-- drops it when fewer than 3 such charges exist. Countries compare without
-- accents, case or spaces: translate() uses the same mapping list_card_transactions
-- uses for merchants, and lower() handles ASCII. A NULL merchant or country makes
-- its column NULL instead of a misleading 0 or FALSE. The aggregate always
-- returns exactly one row. process_date bounds the scan to the window's days.
--
-- Parameters (psycopg named placeholders):
--   customer_id          text       required
--   product_id           text       required
--   transaction_id       text       required, the charge being explained
--   charge_date          timestamp  required, the charge's transaction_date
--   merchant_name        text       nullable
--   currency             text       nullable
--   transaction_country  text       nullable
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster.
--   DISTINCT ON, NULLS LAST, FILTER, percentile_cont, bool_or, translate() and the
--   binds are standard PostgreSQL, but DSQL support is unverified. Column names
--   follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
WITH hist AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.merchant_name, t.amount, t.currency, t.transaction_country
    FROM transactions AS t
    WHERE t.customer_id = %(customer_id)s
      AND t.product_id = %(product_id)s
      AND t.transaction_status = 'Approved'
      AND t.transaction_id <> %(transaction_id)s
      AND t.process_date >= (%(charge_date)s::date - 91)
      AND t.transaction_date >= %(charge_date)s - INTERVAL '90 days'
      AND t.transaction_date <  %(charge_date)s
    ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
)
SELECT COUNT(*) AS history_count,
       CASE WHEN %(merchant_name)s::text IS NULL THEN NULL
            ELSE COUNT(*) FILTER (WHERE merchant_name = %(merchant_name)s::text) END AS times_at_merchant,
       COUNT(*) FILTER (WHERE currency = %(currency)s::text) AS same_currency_count,
       (percentile_cont(0.1) WITHIN GROUP (ORDER BY amount)
            FILTER (WHERE currency = %(currency)s::text))::numeric AS usual_low,
       (percentile_cont(0.9) WITHIN GROUP (ORDER BY amount)
            FILTER (WHERE currency = %(currency)s::text))::numeric AS usual_high,
       CASE WHEN %(transaction_country)s::text IS NULL THEN NULL
            ELSE COALESCE(bool_or(
                lower(translate(btrim(transaction_country), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÑÇáàâãäéèêëíìîïóòôõöúùûüñç', 'AAAAAEEEEIIIIOOOOOUUUUNCaaaaaeeeeiiiiooooouuuunc'))
                = lower(translate(btrim(%(transaction_country)s::text), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÑÇáàâãäéèêëíìîïóòôõöúùûüñç', 'AAAAAEEEEIIIIOOOOOUUUUNCaaaaaeeeeiiiiooooouuuunc'))), FALSE)
       END AS country_seen_before
FROM hist
