-- transaction_app_activity (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The customer's app or web event closest to a charge, within 2 hours either
-- side. Used by ExplainTransactionUseCase for the app_activity section.
--
-- customer_id comes from the core query, which already checked ownership. Only
-- events with an IP country count, because the event is only useful to compare
-- countries. No row is the usual case (D36): few customers have app activity on
-- any given day, and Python reports it as found = false. Python decides whether
-- the countries conflict, and only for in-person channels. process_date bounds
-- the scan to the days around the charge; event_date <= as_of keeps the demo's
-- "now" honest. Ties on distance go to the lower event_id, so the answer is stable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required
--   charge_date  timestamp  required, the charge's transaction_date
--   as_of        timestamp  required, naive UTC
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster.
--   EXTRACT(EPOCH ...), interval arithmetic and the binds are standard PostgreSQL,
--   but DSQL support is unverified. Column names follow docs/LATAM_Bank_ERD.md;
--   smoke-test against a real cluster.
SELECT e.event_id, e.event_date, e.ip_country, e.ip_city
FROM digital_events AS e
WHERE e.customer_id = %(customer_id)s
  AND e.ip_country IS NOT NULL
  AND e.process_date BETWEEN (%(charge_date)s::date - 1) AND (%(charge_date)s::date + 1)
  AND e.event_date BETWEEN %(charge_date)s - INTERVAL '2 hours' AND %(charge_date)s + INTERVAL '2 hours'
  AND e.event_date <= %(as_of)s
ORDER BY ABS(EXTRACT(EPOCH FROM (e.event_date - %(charge_date)s))), e.event_id
LIMIT 1
