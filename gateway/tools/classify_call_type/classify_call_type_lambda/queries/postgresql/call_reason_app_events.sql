-- call_reason_app_events (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The app-event candidates of ClassifyCallTypeUseCase: the customer's app or web
-- errors of the last 24 hours, newest first. Every row is FAILED_APP_ACTION;
-- Python keeps the newest. event_type = 'Error' is the same mapping as
-- get_session_context's FAILED_ACTION signal. A failure here only makes
-- FAILED_APP_ACTION unavailable. process_date bounds the scan to the partition
-- days of the window.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. Interval
--   arithmetic and the binds are standard PostgreSQL, but DSQL support is
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster. digital_events has no index on customer_id; time this query on
--   the deployed stack.
SELECT e.event_id, e.event_date, e.page_title, e.action
FROM digital_events AS e
WHERE e.customer_id = %(customer_id)s
  AND e.event_type = 'Error'
  AND e.process_date >= (%(as_of)s::date - 1)
  AND e.event_date >  %(as_of)s - INTERVAL '24 hours'
  AND e.event_date <= %(as_of)s
ORDER BY e.event_date DESC NULLS LAST, e.event_id
LIMIT 50
