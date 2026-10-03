-- AR-00 Agent-readiness probes over the raw local copy (before repairs R1-R6). as_of = 2026-06-17.
-- Run: python analysis/profile.py analysis/agent_readiness.sql > analysis/agent_readiness_output.txt
-- Cited by docs/analysis/2026-10-02-agent-data-diagnostic.md. Windows use process_date:
-- d7 >= 2026-06-11, d30 >= 2026-05-19, d90 >= 2026-03-19.
SELECT 'as_of 2026-06-17' AS note;

-- AR-SETUP-1 cards with a usable flag: Active, not expired at as_of, credit cards with a limit and not over it
CREATE OR REPLACE TEMP TABLE cards AS
SELECT p.*, (p.product_status = 'Active' AND p.expiration_date >= DATE '2026-06-17'
             AND (p.product_type = 'Tarjeta Débito' OR (p.credit_limit IS NOT NULL AND p.current_balance <= p.credit_limit))) AS usable
FROM products p WHERE p.product_type IN ('Tarjeta Crédito', 'Tarjeta Débito');

-- AR-SETUP-2 card transactions up to as_of with window flags
CREATE OR REPLACE TEMP TABLE card_tx AS
SELECT t.*, c.product_type, c.expiration_date, c.opening_date, c.usable,
       t.process_date >= DATE '2026-05-19' AS d30, t.process_date >= DATE '2026-06-11' AS d7, t.process_date >= DATE '2026-03-19' AS d90
FROM transactions t JOIN cards c USING (product_id) WHERE t.process_date <= DATE '2026-06-17';

-- AR-SETUP-3 one row per customer: what the agent would find for them
CREATE OR REPLACE TEMP TABLE cust AS
WITH cc AS (SELECT customer_id, count(*) FILTER (WHERE usable AND product_type = 'Tarjeta Crédito') usable_cc,
                   count(*) FILTER (WHERE usable AND product_type = 'Tarjeta Débito') usable_dc,
                   count(*) FILTER (WHERE product_status IN ('Blocked', 'Suspended')) blocked_cards
            FROM cards GROUP BY 1),
tx AS (SELECT t.customer_id, count(*) tx_all, count(*) FILTER (WHERE d90) tx90, count(*) FILTER (WHERE d30 AND usable) tx30_usable,
              count(*) FILTER (WHERE d30 AND transaction_status = 'Declined') dec30, count(*) FILTER (WHERE d7 AND transaction_status = 'Declined') dec7,
              count(*) FILTER (WHERE d30 AND transaction_status IN ('Pending', 'Reversed')) pr30,
              count(*) FILTER (WHERE d30 AND lower(strip_accents(t.transaction_country)) <> lower(strip_accents(h.country))) foreign30,
              count(*) FILTER (WHERE d90 AND fraud_score > 30) fraudflag90
       FROM card_tx t JOIN customers h USING (customer_id) GROUP BY 1),
k AS (SELECT customer_id, count(*) FILTER (WHERE creation_date >= TIMESTAMP '2026-03-19') k90,
             count(*) FILTER (WHERE creation_date >= TIMESTAMP '2026-03-19' AND subcategory = 'Cargo no reconocido') unrec90,
             count(*) FILTER (WHERE closing_date IS NULL AND status IN ('Open', 'In Process', 'Escalated') AND creation_date < TIMESTAMP '2026-05-18') stale_open
      FROM complaints WHERE creation_date <= TIMESTAMP '2026-06-17 23:59:59' GROUP BY 1),
i AS (SELECT customer_id, count(*) FILTER (WHERE process_date >= DATE '2026-03-19') calls90 FROM call_center_interactions GROUP BY 1),
e AS (SELECT customer_id, count(*) ev24h FROM digital_events
      WHERE customer_id IS NOT NULL AND event_date > TIMESTAMP '2026-06-16 23:59:59' AND event_date <= TIMESTAMP '2026-06-17 23:59:59' GROUP BY 1)
SELECT c.customer_id, c.first_name, c.country, c.segment, c.customer_status,
       date_diff('year', c.date_of_birth, c.registration_date) age_at_reg, c.email IS NOT NULL AND c.mobile_phone IS NOT NULL AS contactable,
       coalesce(usable_cc, 0) usable_cc, coalesce(usable_dc, 0) usable_dc, coalesce(blocked_cards, 0) blocked_cards,
       coalesce(tx_all, 0) tx_all, coalesce(tx90, 0) tx90, coalesce(tx30_usable, 0) tx30_usable, coalesce(dec30, 0) dec30, coalesce(dec7, 0) dec7,
       coalesce(pr30, 0) pr30, coalesce(foreign30, 0) foreign30, coalesce(fraudflag90, 0) fraudflag90,
       coalesce(k90, 0) k90, coalesce(unrec90, 0) unrec90, coalesce(stale_open, 0) stale_open, coalesce(calls90, 0) calls90, coalesce(ev24h, 0) ev24h
FROM customers c LEFT JOIN cc USING (customer_id) LEFT JOIN tx USING (customer_id) LEFT JOIN k USING (customer_id)
LEFT JOIN i USING (customer_id) LEFT JOIN e USING (customer_id);

-- AR-SETUP-4 the candidate pool and its draft score (section 6 of the diagnostic)
CREATE OR REPLACE TEMP TABLE pool AS
SELECT *, 3 * least(tx30_usable, 5) + 2 * (dec30 > 0)::INT + 2 * (pr30 > 0)::INT + (foreign30 > 0)::INT + 3 * (fraudflag90 > 0)::INT
          + 2 * (unrec90 > 0)::INT + (k90 > 0)::INT + (ev24h > 0)::INT + (calls90 > 0)::INT + (usable_cc + usable_dc >= 2)::INT AS score
FROM cust WHERE customer_status = 'Active' AND age_at_reg >= 18 AND contactable AND usable_cc >= 1 AND tx30_usable >= 1;

-- AR-C1 customer status by country
SELECT country, customer_status, count(*) n FROM customers GROUP BY ALL ORDER BY 1, 3 DESC;

-- AR-C2 document type and mobile prefix by country (Mexico: DNI and +54)
SELECT country, document_type, left(mobile_phone, 3) prefix, count(*) n FROM customers GROUP BY ALL ORDER BY 1, 4 DESC;

-- AR-C3 age, registration and future last_updated
SELECT count(*) FILTER (WHERE date_diff('year', date_of_birth, registration_date) < 18) under18_at_registration,
       min(date_diff('year', date_of_birth, registration_date)) min_age_at_registration,
       count(*) FILTER (WHERE last_updated > TIMESTAMP '2026-06-17 23:59:59') last_updated_after_as_of
FROM customers;

-- AR-C4 missing contact and profile fields
SELECT count(*) FILTER (WHERE email IS NULL) email_null, count(*) FILTER (WHERE mobile_phone IS NULL) mobile_null,
       count(*) FILTER (WHERE address IS NULL) address_null, count(*) FILTER (WHERE credit_score IS NULL) credit_score_null,
       count(*) FILTER (WHERE estimated_monthly_income IS NULL) income_null, count(*) FILTER (WHERE detected_accent IS NULL) accent_null
FROM customers;

-- AR-C5 shared email addresses, and those shared across countries
SELECT count(*) shared_addresses, sum(n) customers_on_them, count(*) FILTER (WHERE countries > 1) shared_across_countries
FROM (SELECT email, count(*) n, count(DISTINCT country) countries FROM customers WHERE email IS NOT NULL GROUP BY 1 HAVING count(*) > 1);

-- AR-C6 gender values
SELECT gender, count(*) FROM customers GROUP BY 1 ORDER BY 1;

-- AR-C7 customer status vs product status (Closed customers holding Active products)
SELECT c.customer_status, p.product_status, count(*) n FROM products p JOIN customers c USING (customer_id) GROUP BY ALL ORDER BY 1, 3 DESC;

-- AR-C8 customers by number of products
SELECT products, count(*) customers FROM (SELECT c.customer_id, count(p.product_id) products FROM customers c LEFT JOIN products p USING (customer_id) GROUP BY 1) GROUP BY 1 ORDER BY 1;

-- AR-C9 first names: compound names and a repeated token ("María María")
SELECT len(string_split(first_name, ' ')) tokens, count(*) n,
       count(*) FILTER (WHERE string_split(first_name, ' ')[1] = string_split(first_name, ' ')[2]) repeated_token
FROM customers GROUP BY 1 ORDER BY 1;

-- AR-C10 gender O: compound names that join a male-list and a female-list name ("Sergio Carolina")
WITH dict AS (SELECT string_split(first_name, ' ')[1] AS nm, min(gender) AS g FROM customers WHERE gender IN ('M', 'F') GROUP BY 1 HAVING count(DISTINCT gender) = 1),
o AS (SELECT string_split(first_name, ' ')[1] AS a, string_split(first_name, ' ')[2] AS b FROM customers WHERE gender = 'O')
SELECT count(*) AS gender_o, count(b) AS compound, count(*) FILTER (WHERE da.g <> db.g) AS mixed_gender_compound
FROM o LEFT JOIN dict da ON da.nm = o.a LEFT JOIN dict db ON db.nm = o.b;

-- AR-P1 card and loan field gaps and contradictions
SELECT product_type, count(*) n, count(*) - count(credit_limit) limit_null, count(*) - count(expiration_date) expiry_null,
       count(*) FILTER (WHERE current_balance > credit_limit) balance_over_limit,
       count(*) FILTER (WHERE product_status = 'Active' AND expiration_date < DATE '2026-06-17') active_but_expired,
       count(*) FILTER (WHERE last_updated > TIMESTAMP '2026-06-17 23:59:59') last_updated_after_as_of
FROM products GROUP BY 1 ORDER BY 2 DESC;

-- AR-P2 product currency by customer country (Mexico has no MXN)
SELECT c.country, p.currency, count(*) n FROM products p JOIN customers c USING (customer_id) GROUP BY ALL ORDER BY 1, 3 DESC;

-- AR-P3 products.last_transaction_date vs the real last transaction
SELECT count(*) products, count(*) FILTER (WHERE p.last_transaction_date IS DISTINCT FROM m.last_tx) mismatched,
       count(*) FILTER (WHERE m.last_tx IS NULL AND p.last_transaction_date IS NOT NULL) date_but_no_transactions,
       count(*) FILTER (WHERE m.last_tx > p.last_transaction_date) transactions_after_it
FROM products p LEFT JOIN (SELECT product_id, max(transaction_date) last_tx FROM transactions GROUP BY 1) m USING (product_id);

-- AR-P4 card numbers: Luhn check digit and same-customer last-4 collisions
WITH d AS (SELECT product_id, product_type, i, (product_number[17 - i])::INT dig FROM cards, generate_series(1, 16) g(i)),
s AS (SELECT product_id, product_type, sum(CASE WHEN i % 2 = 0 THEN (CASE WHEN dig * 2 > 9 THEN dig * 2 - 9 ELSE dig * 2 END) ELSE dig END) tot FROM d GROUP BY ALL)
SELECT product_type, count(*) n, count(*) FILTER (WHERE tot % 10 = 0) luhn_valid,
       (SELECT count(*) FROM (SELECT customer_id, right(product_number, 4) FROM cards GROUP BY ALL HAVING count(*) > 1)) same_customer_last4_pairs
FROM s GROUP BY 1;

-- AR-T1 transaction status x response code
SELECT transaction_status, response_code, count(*) n FROM transactions GROUP BY ALL ORDER BY 1, 3 DESC;

-- AR-T2 card-state contradictions: decline codes vs the card, approvals after expiry
SELECT count(*) FILTER (WHERE t.transaction_status = 'Declined' AND t.response_code = '54' AND p.product_type NOT LIKE 'Tarjeta%') code54_not_a_card,
       count(*) FILTER (WHERE t.transaction_status = 'Declined' AND t.response_code = '54' AND p.product_type LIKE 'Tarjeta%' AND p.expiration_date >= t.transaction_date::DATE) code54_card_not_expired,
       count(*) FILTER (WHERE t.transaction_status = 'Declined' AND p.product_type NOT LIKE 'Tarjeta%') declines_on_non_cards,
       count(*) FILTER (WHERE t.transaction_status = 'Approved' AND p.product_type LIKE 'Tarjeta%' AND t.transaction_date::DATE > p.expiration_date) approved_after_card_expiry
FROM transactions t JOIN products p USING (product_id);

-- AR-T3 Pending/Reversed age at as_of (statuses that never settle)
SELECT transaction_status, count(*) n, count(*) FILTER (WHERE process_date >= DATE '2026-06-11') last7, median(date_diff('day', process_date, DATE '2026-06-17')) median_age_days
FROM transactions WHERE transaction_status IN ('Pending', 'Reversed') GROUP BY 1;

-- AR-T4 product type x transaction type, and channel oddities
SELECT p.product_type, t.transaction_type, count(*) n FROM transactions t JOIN products p USING (product_id) GROUP BY ALL ORDER BY 1, 3 DESC;

-- AR-T5 channel x type oddities (ATM purchases, POS deposits)
SELECT count(*) FILTER (WHERE channel = 'ATM' AND transaction_type = 'Purchase') atm_purchases, count(*) FILTER (WHERE channel = 'POS' AND transaction_type IN ('Deposit', 'Transfer', 'Withdrawal')) pos_non_purchases,
       count(*) FILTER (WHERE transaction_type = 'Purchase' AND merchant_name IS NULL) purchases_without_merchant, count(*) FILTER (WHERE merchant_name IS NOT NULL AND merchant_category IS NULL) merchant_without_category
FROM transactions;

-- AR-T6 home country vs transaction country ('Mexico' unaccented beside 'México')
SELECT c.country home, t.transaction_country, count(*) n FROM transactions t JOIN customers c USING (customer_id) GROUP BY ALL ORDER BY 1, 3 DESC;

-- AR-T7 recency: customers with card transactions in each window
SELECT count(DISTINCT customer_id) FILTER (WHERE process_date >= DATE '2026-06-15') d3, count(DISTINCT customer_id) FILTER (WHERE d7) d7,
       count(DISTINCT customer_id) FILTER (WHERE d30) d30, count(DISTINCT customer_id) FILTER (WHERE d90) d90, count(DISTINCT customer_id) ever
FROM card_tx;

-- AR-T8 credit-card transactions per customer in the last 30 days
SELECT n, count(*) customers FROM (SELECT customer_id, count(*) n FROM card_tx WHERE d30 AND product_type = 'Tarjeta Crédito' GROUP BY 1) GROUP BY 1 ORDER BY 1;

-- AR-T9 recent card transactions by customer status (Closed customers still buying)
SELECT c.customer_status, count(DISTINCT t.customer_id) customers, count(*) tx30 FROM card_tx t JOIN customers c USING (customer_id) WHERE t.d30 GROUP BY 1;

-- AR-V1 card amounts by currency and type (uniform, merchant-independent)
SELECT currency, transaction_type, count(*) n, round(quantile_cont(amount, 0.05), 2) p5, round(median(amount), 2) p50, round(quantile_cont(amount, 0.95), 2) p95, max(amount) max
FROM card_tx GROUP BY ALL ORDER BY 1, 2;

-- AR-V2 median USD amount per merchant (every merchant ~ USD 250)
SELECT min(med) min_merchant_median_usd, max(med) max_merchant_median_usd, count(*) merchants
FROM (SELECT merchant_name, median(CASE WHEN currency = 'USD' THEN amount ELSE amount_usd END) med FROM card_tx WHERE merchant_name IS NOT NULL GROUP BY 1);

-- AR-V3 card purchases by hour of day (flat 24 h)
SELECT min(n) min_per_hour, max(n) max_per_hour FROM (SELECT hour(transaction_date) h, count(*) n FROM card_tx WHERE transaction_type = 'Purchase' GROUP BY 1);

-- AR-V4 credit limit vs monthly income by country (Mexico: USD limits vs peso-scale incomes)
SELECT cu.country, round(median(p.credit_limit)) limit_p50, any_value(p.currency) currency, round(median(cu.estimated_monthly_income)) income_p50,
       round(median(p.credit_limit / nullif(cu.estimated_monthly_income, 0)), 2) limit_to_income
FROM cards p JOIN customers cu USING (customer_id) WHERE p.product_type = 'Tarjeta Crédito' GROUP BY 1;

-- AR-K1 complaint status vs lifecycle fields
SELECT status, count(*) n, count(assignment_date) assigned, count(first_response_date) first_response, count(resolution_date) resolved,
       count(closing_date) closed, count(resolution) resolution_text, count(assigned_agent_id) agent
FROM complaints GROUP BY 1 ORDER BY 2 DESC;

-- AR-K2 complaints without a closing_date: age at as_of by status
SELECT status, count(*) n, median(date_diff('day', creation_date, TIMESTAMP '2026-06-17')) median_age_days,
       count(*) FILTER (WHERE creation_date >= TIMESTAMP '2026-05-18') created_last_30d
FROM complaints WHERE closing_date IS NULL GROUP BY 1 ORDER BY 2 DESC;

-- AR-K3 complaint dates after as_of
SELECT count(*) FILTER (WHERE resolution_date > TIMESTAMP '2026-06-17 23:59:59') resolution_after, count(*) FILTER (WHERE closing_date > TIMESTAMP '2026-06-17 23:59:59') closing_after,
       count(*) FILTER (WHERE first_response_date > TIMESTAMP '2026-06-17 23:59:59') first_response_after
FROM complaints;

-- AR-K4 claimed amount does not scale with its currency
SELECT currency, count(claimed_amount) n, round(median(claimed_amount)) p50, round(quantile_cont(claimed_amount, 0.95)) p95 FROM complaints GROUP BY 1 ORDER BY 1;

-- AR-K5 complaint currency and related branch country vs the customer's country
SELECT c.country, count(*) complaints, count(k.currency) with_currency,
       count(*) FILTER (WHERE k.currency = CASE c.country WHEN 'Argentina' THEN 'ARS' WHEN 'Colombia' THEN 'COP' ELSE 'MXN' END) home_currency,
       count(b.branch_id) with_branch, count(*) FILTER (WHERE b.country = c.country) branch_in_home_country
FROM complaints k JOIN customers c USING (customer_id) LEFT JOIN branches b ON b.branch_id = k.related_branch_id GROUP BY 1;

-- AR-K6 description text is one template per category
SELECT category, count(DISTINCT description) descriptions, any_value(description) example FROM complaints GROUP BY 1;

-- AR-I1 interactions handled by agents hired after the call; agent country vs customer country
SELECT count(*) interactions, count(*) FILTER (WHERE a.hire_date > i.interaction_date::DATE) agent_hired_later,
       count(*) FILTER (WHERE strip_accents(a.country_of_origin) = strip_accents(c.country)) agent_same_country
FROM call_center_interactions i JOIN service_agents a USING (agent_id) JOIN customers c USING (customer_id);

-- AR-I2 mentioned_products: listed ids that exist, and that the caller owns
WITH m AS (SELECT i.customer_id, trim(unnest(string_split(i.mentioned_products, ','))) product_id FROM call_center_interactions i WHERE i.mentioned_products IS NOT NULL)
SELECT count(*) mentions, count(p.product_id) exist, count(*) FILTER (WHERE p.customer_id = m.customer_id) owned_by_caller FROM m LEFT JOIN products p USING (product_id);

-- AR-E1 customers with digital events in the 24 h and 7 days before as_of
SELECT count(DISTINCT customer_id) FILTER (WHERE event_date > TIMESTAMP '2026-06-16 23:59:59') last_24h, count(DISTINCT customer_id) FILTER (WHERE process_date >= DATE '2026-06-11') last_7d
FROM digital_events WHERE customer_id IS NOT NULL AND process_date >= DATE '2026-06-10' AND event_date <= TIMESTAMP '2026-06-17 23:59:59';

-- AR-S1 selection funnel
SELECT count(*) all_customers, count(*) FILTER (WHERE customer_status = 'Active') active,
       count(*) FILTER (WHERE customer_status = 'Active' AND age_at_reg >= 18) adult,
       count(*) FILTER (WHERE customer_status = 'Active' AND age_at_reg >= 18 AND contactable) contactable,
       count(*) FILTER (WHERE customer_status = 'Active' AND age_at_reg >= 18 AND contactable AND usable_cc >= 1) usable_credit_card,
       count(*) FILTER (WHERE customer_status = 'Active' AND age_at_reg >= 18 AND contactable AND usable_cc >= 1 AND tx30_usable >= 1) card_tx_30d,
       count(*) FILTER (WHERE customer_status = 'Active' AND age_at_reg >= 18 AND contactable AND usable_cc >= 1 AND tx30_usable >= 2) card_tx_30d_2plus,
       count(*) FILTER (WHERE customer_status = 'Active' AND age_at_reg >= 18 AND contactable AND usable_cc >= 1 AND tx30_usable >= 3) card_tx_30d_3plus
FROM cust;

-- AR-S2 scenario coverage in the pool
SELECT count(*) pool, count(*) FILTER (WHERE dec7 > 0) decline_7d, count(*) FILTER (WHERE dec30 > 0) decline_30d, count(*) FILTER (WHERE pr30 > 0) pending_or_reversed_30d,
       count(*) FILTER (WHERE foreign30 > 0) foreign_30d, count(*) FILTER (WHERE fraudflag90 > 0) fraud_flag_90d, count(*) FILTER (WHERE unrec90 > 0) unrecognized_charge_case_90d,
       count(*) FILTER (WHERE k90 > 0) any_case_90d, count(*) FILTER (WHERE usable_cc + usable_dc >= 2) two_plus_usable_cards, count(*) FILTER (WHERE blocked_cards > 0) has_blocked_card,
       count(*) FILTER (WHERE ev24h > 0) app_activity_24h, count(*) FILTER (WHERE calls90 > 0) call_90d, count(*) FILTER (WHERE stale_open > 0) stale_open_case
FROM pool;

-- AR-S3 pool by country and segment
SELECT country, segment, count(*) n, count(*) FILTER (WHERE score >= 10) tier_a, count(*) FILTER (WHERE score BETWEEN 7 AND 9) tier_b FROM pool GROUP BY ALL ORDER BY 1, 2;

-- AR-S4 score distribution (cumulative from the top)
SELECT score, count(*) n, sum(count(*)) OVER (ORDER BY score DESC) cumulative FROM pool GROUP BY 1 ORDER BY 1 DESC;

-- AR-S5 defects inside the pool's own rows
SELECT count(*) transactions, count(*) FILTER (WHERE t.transaction_status = 'Pending' AND t.process_date < DATE '2026-06-10') pending_over_7d,
       count(*) FILTER (WHERE t.transaction_status IN ('Pending', 'Reversed') AND t.response_code IS NOT NULL) status_code_mismatch,
       count(*) FILTER (WHERE t.transaction_status = 'Declined' AND t.response_code = '54' AND (p.product_type NOT LIKE 'Tarjeta%' OR p.expiration_date >= t.transaction_date::DATE)) code54_contradiction,
       count(*) FILTER (WHERE p.product_type LIKE 'Tarjeta%' AND t.transaction_date::DATE > p.expiration_date) after_card_expiry,
       count(*) FILTER (WHERE t.transaction_date::DATE < p.opening_date) before_product_opening,
       count(*) FILTER (WHERE t.transaction_country = 'Mexico') unaccented_mexico
FROM transactions t JOIN pool USING (customer_id) JOIN products p USING (product_id);

-- AR-S6 rows a pool-only database would hold
SELECT (SELECT count(*) FROM pool) customers, (SELECT count(*) FROM products JOIN pool USING (customer_id)) products,
       (SELECT count(*) FROM transactions JOIN pool USING (customer_id)) transactions, (SELECT count(*) FROM complaints JOIN pool USING (customer_id)) complaints,
       (SELECT count(*) FROM call_center_interactions JOIN pool USING (customer_id)) interactions, (SELECT count(*) FROM call_transcripts JOIN pool USING (customer_id)) transcripts,
       (SELECT count(*) FROM satisfaction_surveys JOIN pool USING (customer_id)) surveys, (SELECT count(*) FROM digital_events JOIN pool USING (customer_id)) digital_events,
       (SELECT count(*) FROM campaign_sends JOIN pool USING (customer_id)) campaign_sends;

-- AR-S7 top 40 candidates
SELECT customer_id, first_name, country, segment, score, usable_cc, usable_dc, tx_all, tx90, tx30_usable, dec30, pr30, foreign30, fraudflag90, k90, unrec90, calls90, ev24h, stale_open
FROM pool ORDER BY score DESC, tx90 DESC, customer_id LIMIT 40
