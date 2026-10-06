-- session_open_cases (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Complaints and claims open at as_of, SLA breaches first, then the newest. Used
-- by GetSessionContextUseCase; a failure here only makes the open_cases section
-- unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--   limit        integer    max rows plus one (the extra row marks the section truncated)
--
-- "Open at as_of" means created on or before as_of and not closed by then, so a
-- case closed today still counts on a past demo date. status is returned as it is
-- stored now, so on a past AS_OF it can read Closed (risk C3, accepted for demos).
-- Some Resolved/Closed rows have no closing_date; without a date, status decides,
-- so those don't show up as open forever.
-- date minus date is an integer in PostgreSQL, so days_open maps to an int.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. Column
--   names follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time, keeping the latest process_date. Drop it once the data
--   load deduplicates.
SELECT deduplicated.complaint_id,
       deduplicated.case_type,
       deduplicated.category,
       deduplicated.subcategory,
       deduplicated.status,
       deduplicated.priority,
       deduplicated.sla_breached,
       deduplicated.claimed_amount,
       deduplicated.currency,
       (%(as_of)s::date - deduplicated.creation_date::date) AS days_open
FROM (
    SELECT DISTINCT ON (k.complaint_id) k.*
    FROM complaints AS k
    WHERE k.customer_id = %(customer_id)s
      AND k.creation_date <= %(as_of)s
      AND (k.closing_date > %(as_of)s
           OR (k.closing_date IS NULL AND k.status NOT IN ('Resolved', 'Closed')))
    ORDER BY k.complaint_id, k.process_date DESC NULLS LAST
) AS deduplicated
ORDER BY deduplicated.sla_breached DESC NULLS LAST,
         deduplicated.creation_date DESC NULLS LAST,
         deduplicated.complaint_id
LIMIT %(limit)s
