-- session_customer_profile (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The customer's profile for the session snapshot. Used by
-- GetSessionContextUseCase; it is the core section, so its failure fails the call.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text  required (the use case strips and uppercases it)
--
-- Sensitive columns (document, date of birth, gender, contact details, credit
-- score, income) are deliberately not selected. No column list wildcard is used,
-- so a new column never leaks by accident.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON
--   and NULLS LAST are standard PostgreSQL, but DSQL support is unverified. Column
--   names follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time, keeping the latest last_updated. Drop it once the data
--   load deduplicates.
SELECT DISTINCT ON (c.customer_id)
       c.customer_id,
       c.first_name,
       c.country,
       c.city,
       c.customer_status
FROM customers AS c
WHERE c.customer_id = %(customer_id)s
ORDER BY c.customer_id, c.last_updated DESC NULLS LAST
