-- resolution_estimate (PostgreSQL dialect, runs on Aurora DSQL)
--
-- How long similar claims took to resolve over the last year: the median and the
-- 90th percentile of resolution_days. Used by OpenClaimUseCase after the claims
-- are written; any failure here is logged and gives no estimate.
--
-- Parameters (psycopg named placeholders):
--   subcategory  text       required, the claim's subcategory
--   since        timestamp  required, the claim's creation date minus 365 days
--
-- With fewer than 20 cases no row comes back: no estimate from too few cases.
-- compensation_granted is never read: quoting it would sound like a promise.
--
-- TODO(ledgerlens): W1 - percentile_cont not yet run on a real Aurora DSQL cluster.
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_days) AS median_days,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_days) AS p90_days
FROM complaints
WHERE case_type = 'Claim'
  AND category = 'Transactions'
  AND subcategory = %(subcategory)s
  AND resolution_days IS NOT NULL
  AND creation_date >= %(since)s
HAVING COUNT(*) >= 20
