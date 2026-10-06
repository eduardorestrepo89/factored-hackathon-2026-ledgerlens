-- [S1] row counts per table (compare with documented counts)
SELECT 'customers' t, count(*) n FROM customers UNION ALL SELECT 'products', count(*) FROM products
UNION ALL SELECT 'branches', count(*) FROM branches UNION ALL SELECT 'service_agents', count(*) FROM service_agents
UNION ALL SELECT 'marketing_campaigns', count(*) FROM marketing_campaigns UNION ALL SELECT 'daily_exchange_rates', count(*) FROM daily_exchange_rates
UNION ALL SELECT 'transactions', count(*) FROM transactions UNION ALL SELECT 'call_center_interactions', count(*) FROM call_center_interactions
UNION ALL SELECT 'call_transcripts', count(*) FROM call_transcripts UNION ALL SELECT 'satisfaction_surveys', count(*) FROM satisfaction_surveys
UNION ALL SELECT 'digital_events', count(*) FROM digital_events UNION ALL SELECT 'complaints', count(*) FROM complaints
UNION ALL SELECT 'campaign_sends', count(*) FROM campaign_sends;

-- [D1] contact reason mix (reason_category vs contact_reason)
SELECT contact_reason, reason_category, count(*) n, round(100.0*count(*)/sum(count(*)) over(),2) pct FROM call_center_interactions GROUP BY ALL ORDER BY n DESC;

-- [D2] channel x interaction type
SELECT channel, interaction_type, count(*) n FROM call_center_interactions GROUP BY ALL ORDER BY n DESC;

-- [D3] KPIs by contact reason
SELECT contact_reason, count(*) n,
 round(avg(was_resolved::int)*100,1) fcr_pct, round(avg(was_escalated::int)*100,1) esc_pct, round(avg(requires_followup::int)*100,1) followup_pct,
 median(duration_seconds) med_duration_s, median(wait_time_seconds) med_wait_s, round(avg(sentiment_score),3) avg_sentiment, round(avg(has_transcript::int)*100,1) transcript_pct
FROM call_center_interactions GROUP BY ALL ORDER BY n DESC;

-- [D4] quarterly volume
SELECT year(interaction_date) || '-Q' || quarter(interaction_date) q, count(*) n, count(*) FILTER (WHERE contact_reason='Queja') queja, count(*) FILTER (WHERE channel<>'Phone') non_phone FROM call_center_interactions GROUP BY ALL ORDER BY 1;

-- [D5] day of week: business date (process_date) vs raw timestamp
SELECT d dow, count(*) FILTER (WHERE k='business') n_by_business_date, count(*) FILTER (WHERE k='raw') n_by_raw_timestamp
FROM (SELECT isodow(process_date) d, 'business' k FROM call_center_interactions UNION ALL SELECT isodow(interaction_date), 'raw' FROM call_center_interactions) GROUP BY 1 ORDER BY 1;

-- [D6] hour of day (raw timestamps)
SELECT hour(interaction_date) h, count(*) n FROM call_center_interactions GROUP BY ALL ORDER BY h;

-- [D7] CSAT by resolution and escalation
SELECT i.was_resolved, i.was_escalated, count(*) n, round(avg(s.main_score),3) csat FROM satisfaction_surveys s JOIN call_center_interactions i USING(interaction_id) WHERE s.survey_type='CSAT' GROUP BY ALL ORDER BY 1,2;

-- [D8] CSAT by detected sentiment
SELECT i.detected_sentiment, count(*) n, round(avg(s.main_score),3) csat FROM satisfaction_surveys s JOIN call_center_interactions i USING(interaction_id) WHERE s.survey_type='CSAT' GROUP BY ALL ORDER BY csat;

-- [D9] accent match vs FCR
SELECT (customer_detected_accent = agent_used_accent) accent_match, count(*) n, round(avg(was_resolved::int)*100,2) fcr, round(avg(sentiment_score),4) sentiment, round(avg(duration_seconds)) avg_duration FROM call_center_interactions WHERE customer_detected_accent IS NOT NULL GROUP BY ALL;

-- [D10] FCR / escalation / wait by country and segment
SELECT c.country, c.segment, count(*) n, round(avg(i.was_resolved::int)*100,2) fcr, round(avg(i.was_escalated::int)*100,2) esc, median(i.wait_time_seconds) med_wait FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY ALL ORDER BY 1,2;

-- [D11] agent-level FCR spread (agents with >200 contacts)
WITH a AS (SELECT agent_id, count(*) n, avg(was_resolved::int) fcr FROM call_center_interactions GROUP BY 1 HAVING count(*)>200)
SELECT count(*) agents, median(n) med_contacts, round(min(fcr)*100,1) min_fcr, round(quantile_cont(fcr,0.05)*100,1) p5, round(median(fcr)*100,1) med, round(quantile_cont(fcr,0.95)*100,1) p95, round(max(fcr)*100,1) max_fcr FROM a;

-- [D12] contacts per customer
SELECT k contacts, count(*) customers FROM (SELECT customer_id, count(*) k FROM call_center_interactions GROUP BY 1) GROUP BY 1 ORDER BY 1;

-- [D13] agent time by contact reason (contacts with a duration only)
SELECT contact_reason, count(*) n, count(duration_seconds) with_duration, round(avg(duration_seconds)) mean_s, median(duration_seconds) med_s, round(sum(duration_seconds)/3600) total_agent_hours FROM call_center_interactions GROUP BY ALL ORDER BY total_agent_hours DESC;

-- [D14] historical routing: agent specialty vs contact reason (random => no escalation ground truth)
SELECT coalesce(a.specialty,'(none)') specialty, count(*) n, round(avg((i.contact_reason='Queja')::int)*100,1) queja_pct, round(avg((i.contact_reason='Transaccional')::int)*100,1) transaccional_pct FROM call_center_interactions i JOIN service_agents a USING(agent_id) GROUP BY 1 ORDER BY 1;

-- [D15] survey scores are a fixed function of was_resolved
SELECT s.survey_type, i.was_resolved, list(DISTINCT s.main_score ORDER BY s.main_score) score_values, round(avg(s.main_score),2) mean_score FROM satisfaction_surveys s JOIN call_center_interactions i USING(interaction_id) GROUP BY ALL ORDER BY 1,2;

-- [T1] transcript language
SELECT detected_language, count(*) n FROM call_transcripts GROUP BY ALL;

-- [T2] transcript detected_intents
SELECT detected_intents, count(*) n FROM call_transcripts GROUP BY ALL ORDER BY n DESC;

-- [T3] transcript text diversity
SELECT count(*) n, count(DISTINCT full_text) distinct_full_text, count(DISTINCT customer_text) distinct_customer_text, count(DISTINCT agent_text) distinct_agent_text FROM call_transcripts;

-- [T4] unfilled placeholders
SELECT tok, count(*) n, (SELECT count(*) FROM call_transcripts WHERE full_text LIKE '%{%}%') transcripts_with_placeholder FROM (SELECT unnest(regexp_extract_all(full_text, '\{[a-z_]+\}')) tok FROM call_transcripts) GROUP BY 1 ORDER BY n DESC;

-- [T5] distinct customer sentences
SELECT s, count(*) n FROM (SELECT unnest(string_split_regex(customer_text, '[.?!]\s+')) s FROM call_transcripts) GROUP BY 1 ORDER BY n DESC;

-- [T6] distinct agent sentences (note: no identity-verification sentence exists)
SELECT s, count(*) n FROM (SELECT unnest(string_split_regex(agent_text, '[.?!]\s+')) s FROM call_transcripts) GROUP BY 1 ORDER BY n DESC;

-- [T7] transcript opening vs labelled contact reason (text is independent of label)
SELECT CASE WHEN t.customer_text LIKE '%tarjeta de crédito%' THEN 'credit_card_balance' WHEN t.customer_text LIKE '%cuenta de ahorros%' THEN 'savings_balance' ELSE 'other' END script,
 i.contact_reason, count(*) n FROM call_transcripts t JOIN call_center_interactions i USING(interaction_id) GROUP BY ALL ORDER BY 1, n DESC;

-- [T8] main_topics is a copy of contact_reason
SELECT round(avg((t.main_topics = i.contact_reason)::int)*100,2) pct_equal, count(*) n FROM call_transcripts t JOIN call_center_interactions i USING(interaction_id);

-- [T9] free-text diversity in complaints and surveys
SELECT (SELECT count(DISTINCT description) FROM complaints) complaint_descriptions, (SELECT count(DISTINCT resolution) FROM complaints) complaint_resolutions, (SELECT count(DISTINCT open_comments) FROM satisfaction_surveys) survey_comments;

-- [C1] complaint category x subcategory
SELECT category, subcategory, count(*) n, round(100.0*count(*)/sum(count(*)) over(),2) pct, round(avg(sla_breached::int)*100,1) sla_breach_pct, median(resolution_days) med_res_days, round(avg(claimed_amount)) avg_claimed, round(avg(resolution_satisfaction),2) res_sat FROM complaints GROUP BY ALL ORDER BY n DESC;

-- [C2] complaint case_type and reception channel
SELECT case_type, reception_channel, count(*) n, round(avg(sla_breached::int)*100,1) sla_breach_pct FROM complaints GROUP BY ALL ORDER BY n DESC;

-- [C3] complaint status share (overall and 2023 cohort)
SELECT 'all' cohort, round(avg((status IN ('Open','In Process'))::int)*100,1) open_or_in_process_pct, round(avg((status IN ('Open','In Process','Escalated'))::int)*100,1) unresolved_pct, round(avg((resolution IS NULL)::int)*100,1) no_resolution_text_pct FROM complaints
UNION ALL SELECT '2023', round(avg((status IN ('Open','In Process'))::int)*100,1), round(avg((status IN ('Open','In Process','Escalated'))::int)*100,1), round(avg((resolution IS NULL)::int)*100,1) FROM complaints WHERE year(creation_date)=2023;

-- [C4] complaint link fill rates
SELECT count(*) n, count(origin_interaction_id) with_origin_interaction, count(affected_product_id) with_product, count(claimed_amount) with_amount, count(assigned_agent_id) assigned, round(avg(is_repeat_complainer::int)*100,1) repeat_pct FROM complaints;

-- [C5] complaint date coherence
SELECT count(*) FILTER (WHERE first_response_date < creation_date) resp_before_create, count(*) FILTER (WHERE status IN ('Resolved','Closed') AND resolution_date IS NULL) resolved_without_date, count(*) FILTER (WHERE resolution_days <> datediff('day', creation_date, resolution_date)) days_mismatch FROM complaints;

-- [C6] complaint category -> subcategory is 1:1
SELECT category, count(DISTINCT subcategory) n_subcategories, string_agg(DISTINCT subcategory, '|') subcategory FROM complaints GROUP BY 1 ORDER BY 1;

-- [C7] complaint priority is independent of category; SLA breach and first response independent of priority
SELECT 'category=' || category k, count(*) n, round(avg((priority IN ('High','Critical'))::int)*100,1) high_or_critical_pct, NULL sla_breach_pct, NULL med_first_response_h FROM complaints GROUP BY 1
UNION ALL SELECT 'priority=' || priority, count(*), NULL, round(avg(sla_breached::int)*100,1), median(datediff('hour', creation_date, first_response_date)) FROM complaints GROUP BY 1 ORDER BY 1;

-- [C8] is_repeat_complainer vs actual complaint in prior 90 days
WITH h AS (SELECT is_repeat_complainer, creation_date, lag(creation_date) OVER (PARTITION BY customer_id ORDER BY creation_date) prev FROM complaints)
SELECT is_repeat_complainer, count(*) n, round(avg(coalesce(prev >= creation_date - INTERVAL 90 DAY, false)::int)*100,2) actual_prior_90d_pct FROM h GROUP BY 1;

-- [C9] complaint currency vs customer country (random)
SELECT cu.country, c.currency, count(*) n FROM complaints c JOIN customers cu USING(customer_id) GROUP BY ALL ORDER BY 1, n DESC;

-- [X1] transaction type x status
SELECT transaction_type, transaction_status, count(*) n FROM transactions GROUP BY ALL ORDER BY 1, n DESC;

-- [X2] transaction status x response code
SELECT transaction_status, response_code, count(*) n, round(avg(is_fraud::int)*100,2) fraud_pct FROM transactions GROUP BY ALL ORDER BY 1, n DESC;

-- [X3] fraud rate by fraud_score bucket
SELECT CASE WHEN fraud_score IS NULL THEN 'null' WHEN fraud_score<20 THEN '00-20' WHEN fraud_score<50 THEN '20-50' WHEN fraud_score<80 THEN '50-80' ELSE '80-100' END bucket, count(*) n, sum(is_fraud::int) fraud, round(avg(is_fraud::int)*100,2) fraud_pct FROM transactions GROUP BY ALL ORDER BY 1;

-- [X4] composition of fraud labels by score
SELECT count(*) fraud, count(*) FILTER (WHERE fraud_score>=50) score_ge_50, count(*) FILTER (WHERE fraud_score<50) score_lt_50, count(*) FILTER (WHERE fraud_score IS NULL) score_null FROM transactions WHERE is_fraud;

-- [X15] exact fraud_score boundary: non-fraud scores never exceed 30
SELECT max(fraud_score) FILTER (WHERE NOT is_fraud) max_nonfraud_score, count(*) FILTER (WHERE fraud_score > 30) score_gt_30, count(*) FILTER (WHERE fraud_score > 30 AND is_fraud) fraud_gt_30, count(*) FILTER (WHERE is_fraud) fraud FROM transactions;

-- [X5] transaction country x currency
SELECT transaction_country, currency, count(*) n FROM transactions GROUP BY ALL ORDER BY 1, n DESC;

-- [X6] amount_usd fill by currency
SELECT currency, count(*) n, count(amount_usd) with_usd, median(amount) med_amount, median(amount_usd) med_usd FROM transactions GROUP BY ALL;

-- [X7] product type x status
SELECT product_type, product_status, count(*) n FROM products GROUP BY ALL ORDER BY 1, n DESC;

-- [X8] credit products: limits, delinquency, expiry
SELECT product_type, count(*) n, count(credit_limit) with_limit, median(credit_limit) med_limit, round(avg((days_past_due>0)::int)*100,1) dpd_pos_pct_of_nonnull, round(100.0*count(*) FILTER (WHERE days_past_due>0)/count(*),1) dpd_pos_pct_of_all, max(days_past_due) max_dpd, round(avg(interest_rate),2) avg_rate, count(expiration_date) with_expiry FROM products GROUP BY ALL ORDER BY n DESC;

-- [X9] active-but-expired products and over-limit balances (as of dataset end 2026-06-17)
SELECT product_type, count(*) FILTER (WHERE expiration_date < DATE '2026-06-17' AND product_status='Active') active_expired, count(*) FILTER (WHERE credit_limit IS NOT NULL AND current_balance > credit_limit) over_limit, count(*) FILTER (WHERE product_status='Active' AND credit_limit IS NOT NULL AND current_balance > credit_limit) over_limit_active FROM products GROUP BY ALL ORDER BY 1;

-- [X10] product currency by owner country
SELECT c.country, p.currency, count(*) n FROM products p JOIN customers c USING(customer_id) GROUP BY ALL ORDER BY 1, n DESC;

-- [X11] transactions on currently non-active products
SELECT p.product_status, count(*) n FROM transactions t JOIN products p USING(product_id) GROUP BY ALL;

-- [X12] transactions outside product lifetime fields
SELECT count(*) n, count(*) FILTER (WHERE t.transaction_date::date < p.opening_date) before_opening, count(*) FILTER (WHERE t.transaction_date > p.last_transaction_date) after_last_txn_field FROM transactions t JOIN products p USING(product_id);

-- [X13] transaction types on loans / insurance / investments
SELECT p.product_type, t.transaction_type, count(*) n FROM transactions t JOIN products p USING(product_id) WHERE p.product_type IN ('Préstamo Hipotecario','Préstamo Personal','Seguro','Inversión') GROUP BY ALL ORDER BY 1, n DESC;

-- [X14] transaction channel x type (implausible combinations such as ATM Purchase, POS Deposit)
SELECT channel, transaction_type, count(*) n FROM transactions GROUP BY ALL ORDER BY 1, n DESC;

-- [A1] transaction product belongs to transaction customer
SELECT count(*) n, count(*) FILTER (WHERE p.customer_id = t.customer_id) owner_match FROM transactions t JOIN products p USING(product_id);

-- [A2] complaint affected_product belongs to complainant
SELECT count(*) n, count(*) FILTER (WHERE p.customer_id = x.customer_id) owner_match FROM complaints x JOIN products p ON p.product_id = x.affected_product_id;

-- [A3] interaction mentioned_products belong to caller
WITH m AS (SELECT customer_id cid, trim(unnest(string_split(mentioned_products, ','))) pid FROM call_center_interactions WHERE mentioned_products IS NOT NULL)
SELECT count(*) refs, count(*) FILTER (WHERE p.customer_id = m.cid) owned_by_caller, count(*) FILTER (WHERE p.product_id IS NULL) nonexistent FROM m LEFT JOIN products p ON p.product_id = m.pid;

-- [A4] transcript vs interaction consistency
SELECT count(*) n, count(*) FILTER (WHERE t.customer_id=i.customer_id) same_customer, count(*) FILTER (WHERE t.agent_id=i.agent_id) same_agent, count(*) FILTER (WHERE t.duration_seconds=i.duration_seconds) same_duration FROM call_transcripts t JOIN call_center_interactions i USING(interaction_id);

-- [A14] digital_events.product_id belongs to the event's customer (third ownership trap)
SELECT count(*) n_events_with_customer_and_product, count(*) FILTER (WHERE p.customer_id = d.customer_id) owner_match FROM digital_events d JOIN products p USING(product_id) WHERE d.customer_id IS NOT NULL;

-- [A12] active Portuguese-speaking agents in dispute-relevant specialties, by shift
SELECT specialty, work_shift, count(*) FILTER (WHERE languages LIKE '%portugu%') pt_active, count(*) all_active FROM service_agents WHERE agent_status='Active' AND specialty IN ('Fraudes','Quejas y Reclamos') GROUP BY ALL ORDER BY 1,2;

-- [A5] shared email addresses
SELECT count(*) shared_emails, sum(k) customers_on_shared_emails, (SELECT count(*) FROM customers WHERE email IS NULL) null_emails FROM (SELECT email, count(*) k FROM customers WHERE email IS NOT NULL GROUP BY 1 HAVING count(*)>1);

-- [A6] document type by country
SELECT country, document_type, count(*) n FROM customers GROUP BY ALL ORDER BY 1, n DESC;

-- [A7] mobile phone prefix by country
SELECT country, left(mobile_phone,3) prefix, count(*) n FROM customers GROUP BY ALL ORDER BY 1, n DESC;

-- [A8] campaign sends vs marketing consent
SELECT c.accepts_marketing, count(*) sends FROM campaign_sends s JOIN customers c USING(customer_id) GROUP BY ALL;

-- [A9] contacts by customer status
SELECT c.customer_status, count(*) n FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY ALL ORDER BY n DESC;

-- [A10] agent languages
SELECT languages, count(*) n, count(*) FILTER (WHERE agent_status='Active') active FROM service_agents GROUP BY ALL ORDER BY n DESC;

-- [A11] agent specialties
SELECT specialty, count(*) n, count(*) FILTER (WHERE agent_status='Active') active FROM service_agents GROUP BY ALL ORDER BY n DESC;

-- [Q1] primary-key duplicates
SELECT 'customers' t, count(*)-count(DISTINCT customer_id) pk_dups FROM customers UNION ALL SELECT 'products', count(*)-count(DISTINCT product_id) FROM products
UNION ALL SELECT 'transactions', count(*)-count(DISTINCT transaction_id) FROM transactions UNION ALL SELECT 'interactions', count(*)-count(DISTINCT interaction_id) FROM call_center_interactions
UNION ALL SELECT 'transcripts', count(*)-count(DISTINCT transcript_id) FROM call_transcripts UNION ALL SELECT 'complaints', count(*)-count(DISTINCT complaint_id) FROM complaints
UNION ALL SELECT 'surveys', count(*)-count(DISTINCT survey_id) FROM satisfaction_surveys UNION ALL SELECT 'digital_events', count(*)-count(DISTINCT event_id) FROM digital_events
UNION ALL SELECT 'campaign_sends', count(*)-count(DISTINCT send_id) FROM campaign_sends UNION ALL SELECT 'fx', count(*)-count(DISTINCT (date, source_currency, target_currency)) FROM daily_exchange_rates;

-- [Q2] content duplicates (same business content, different id)
SELECT 'transactions' t, count(*) - count(DISTINCT (customer_id, product_id, transaction_date, amount, transaction_type)) content_dups FROM transactions
UNION ALL SELECT 'interactions', count(*) - count(DISTINCT (customer_id, interaction_date, contact_reason, channel)) FROM call_center_interactions
UNION ALL SELECT 'complaints', count(*) - count(DISTINCT (customer_id, creation_date, category)) FROM complaints
UNION ALL SELECT 'digital_events', count(*) - count(DISTINCT (session_id, event_date, event_type)) FROM digital_events;

-- [Q3] orphan foreign keys
SELECT 'transactions.customer_id' fk, count(*) FILTER (WHERE c.customer_id IS NULL) orphans FROM transactions t LEFT JOIN customers c USING(customer_id)
UNION ALL SELECT 'transactions.product_id', count(*) FILTER (WHERE p.product_id IS NULL) FROM transactions t LEFT JOIN products p USING(product_id)
UNION ALL SELECT 'interactions.customer_id', count(*) FILTER (WHERE c.customer_id IS NULL) FROM call_center_interactions i LEFT JOIN customers c USING(customer_id)
UNION ALL SELECT 'interactions.agent_id', count(*) FILTER (WHERE a.agent_id IS NULL AND i.agent_id IS NOT NULL) FROM call_center_interactions i LEFT JOIN service_agents a USING(agent_id)
UNION ALL SELECT 'transcripts.interaction_id', count(*) FILTER (WHERE i.interaction_id IS NULL) FROM call_transcripts t LEFT JOIN call_center_interactions i USING(interaction_id)
UNION ALL SELECT 'complaints.customer_id', count(*) FILTER (WHERE c.customer_id IS NULL) FROM complaints x LEFT JOIN customers c USING(customer_id)
UNION ALL SELECT 'complaints.affected_product_id', count(*) FILTER (WHERE p.product_id IS NULL AND x.affected_product_id IS NOT NULL) FROM complaints x LEFT JOIN products p ON p.product_id = x.affected_product_id
UNION ALL SELECT 'products.customer_id', count(*) FILTER (WHERE c.customer_id IS NULL) FROM products p LEFT JOIN customers c USING(customer_id)
UNION ALL SELECT 'surveys.interaction_id', count(*) FILTER (WHERE i.interaction_id IS NULL) FROM satisfaction_surveys s LEFT JOIN call_center_interactions i USING(interaction_id)
UNION ALL SELECT 'surveys.agent_id', count(*) FILTER (WHERE a.agent_id IS NULL AND s.agent_id IS NOT NULL) FROM satisfaction_surveys s LEFT JOIN service_agents a USING(agent_id)
UNION ALL SELECT 'campaign_sends.campaign_id', count(*) FILTER (WHERE m.campaign_id IS NULL) FROM campaign_sends s LEFT JOIN marketing_campaigns m USING(campaign_id)
UNION ALL SELECT 'customers.registration_branch_id', count(*) FILTER (WHERE b.branch_id IS NULL) FROM customers c LEFT JOIN branches b ON b.branch_id = c.registration_branch_id
UNION ALL SELECT 'products.opening_branch_id', count(*) FILTER (WHERE b.branch_id IS NULL) FROM products p LEFT JOIN branches b ON b.branch_id = p.opening_branch_id
UNION ALL SELECT 'service_agents.assigned_branch_id', count(*) FILTER (WHERE b.branch_id IS NULL AND a.assigned_branch_id IS NOT NULL) FROM service_agents a LEFT JOIN branches b ON b.branch_id = a.assigned_branch_id
UNION ALL SELECT 'transactions.branch_id', count(*) FILTER (WHERE b.branch_id IS NULL AND t.branch_id IS NOT NULL) FROM transactions t LEFT JOIN branches b ON b.branch_id = t.branch_id
UNION ALL SELECT 'complaints.related_branch_id', count(*) FILTER (WHERE b.branch_id IS NULL AND x.related_branch_id IS NOT NULL) FROM complaints x LEFT JOIN branches b ON b.branch_id = x.related_branch_id;

-- [Q4] process_date minus event date per table, with time-of-day range (per-table batch cutoff, not late data)
SELECT 'transactions' t, datediff('day', transaction_date::date, process_date) lag_days, count(*) n, min(strftime(transaction_date,'%H:%M')) min_hhmm, max(strftime(transaction_date,'%H:%M')) max_hhmm FROM transactions GROUP BY ALL
UNION ALL SELECT 'interactions', datediff('day', interaction_date::date, process_date), count(*), min(strftime(interaction_date,'%H:%M')), max(strftime(interaction_date,'%H:%M')) FROM call_center_interactions GROUP BY ALL
UNION ALL SELECT 'complaints', datediff('day', creation_date::date, process_date), count(*), min(strftime(creation_date,'%H:%M')), max(strftime(creation_date,'%H:%M')) FROM complaints GROUP BY ALL
UNION ALL SELECT 'surveys', datediff('day', survey_date::date, process_date), count(*), min(strftime(survey_date,'%H:%M')), max(strftime(survey_date,'%H:%M')) FROM satisfaction_surveys GROUP BY ALL
UNION ALL SELECT 'digital_events', datediff('day', event_date::date, process_date), count(*), min(strftime(event_date,'%H:%M')), max(strftime(event_date,'%H:%M')) FROM digital_events GROUP BY ALL ORDER BY 1, 2;

-- [Q4b] the cutoff is the same for every customer country (so not a customer timezone)
SELECT c.country, round(avg((datediff('day', i.interaction_date::date, i.process_date) = -1)::int)*100,1) interactions_prev_day_pct FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY 1;

-- [Q13] future-dated fields relative to the dataset end (2026-06-17 business day)
SELECT (SELECT max(last_updated) FROM customers) customers_max_last_updated, (SELECT max(last_updated) FROM products) products_max_last_updated, (SELECT max(resolution_date) FROM complaints) complaints_max_resolution, (SELECT count(*) FROM complaints WHERE resolution_date > TIMESTAMP '2026-06-18 08:00') resolutions_after_end, (SELECT count(*) FROM complaints WHERE first_response_date::date > process_date) first_response_after_file_date;

-- [Q5] partition file date vs process_date, and event timestamp range
SELECT count(*) FILTER (WHERE strftime(process_date, '%Y%m%d') <> regexp_extract(filename, '(\d{8})\.csv', 1)) file_date_mismatch, min(transaction_date) min_ts, max(transaction_date) max_ts, min(process_date) min_pd, max(process_date) max_pd FROM transactions;

-- [Q6] FX coverage and range
SELECT source_currency, target_currency, count(*) n, min(date) first_day, max(date) last_day, round(min(exchange_rate),4) min_rate, round(max(exchange_rate),4) max_rate FROM daily_exchange_rates GROUP BY ALL ORDER BY 1,2;

-- [Q7] amount_usd consistency with FX table
SELECT t.currency, count(*) n, round(avg(abs(t.amount_usd - t.amount*f.exchange_rate)),2) mean_abs_err_usd, round(avg(t.amount_usd/(t.amount*f.exchange_rate)),4) mean_ratio FROM transactions t JOIN daily_exchange_rates f ON f.date=t.process_date AND f.source_currency=t.currency AND f.target_currency='USD' WHERE t.amount_usd IS NOT NULL GROUP BY ALL;

-- [Q8] customers by country and segment
SELECT country, segment, count(*) n, round(avg(credit_score)) avg_credit_score, median(estimated_monthly_income) med_income FROM customers GROUP BY ALL ORDER BY 1, n DESC;

-- [Q9] sentiment label ranges
SELECT detected_sentiment, count(*) n, min(sentiment_score) min_s, max(sentiment_score) max_s FROM call_center_interactions GROUP BY ALL ORDER BY n DESC;

-- [Q10] survey scales and NPS categories
SELECT survey_type, nps_category, count(*) n, min(main_score) min_score, max(main_score) max_score FROM satisfaction_surveys GROUP BY ALL ORDER BY 1, 2;

-- [Q11] digital events: types, anonymous share, IP country vs customer country
SELECT event_type, event_category, count(*) n, round(avg((customer_id IS NULL)::int)*100,1) anonymous_pct FROM digital_events GROUP BY ALL ORDER BY n DESC;

-- [Q12] digital IP country vs customer home country
SELECT c.country, d.ip_country, count(*) n FROM digital_events d JOIN customers c USING(customer_id) GROUP BY ALL ORDER BY 1, n DESC;

-- [K1] declined transaction -> any contact within 7 days (full population)
WITH x AS (SELECT t.transaction_id, t.transaction_status, max(CASE WHEN i.interaction_id IS NOT NULL THEN 1 ELSE 0 END) contacted
  FROM transactions t LEFT JOIN call_center_interactions i ON i.customer_id=t.customer_id AND i.interaction_date > t.transaction_date AND i.interaction_date <= t.transaction_date + INTERVAL 7 DAY GROUP BY ALL)
SELECT transaction_status, count(*) n, sum(contacted) contacted, round(avg(contacted)*100,3) contact_7d_pct FROM x GROUP BY ALL ORDER BY 1;

-- [K2] digital error vs login -> any contact within 1 day (full population)
WITH x AS (SELECT d.event_id, d.event_type, max(CASE WHEN i.interaction_id IS NOT NULL THEN 1 ELSE 0 END) contacted
  FROM digital_events d LEFT JOIN call_center_interactions i ON i.customer_id=d.customer_id AND i.interaction_date > d.event_date AND i.interaction_date <= d.event_date + INTERVAL 1 DAY
  WHERE d.customer_id IS NOT NULL AND d.event_type IN ('Error','Login') GROUP BY ALL)
SELECT event_type, count(*) n, sum(contacted) contacted, round(avg(contacted)*100,3) contact_1d_pct FROM x GROUP BY ALL;

-- [K3] fraud transaction -> complaint within 30 days (full population)
WITH x AS (SELECT t.transaction_id, t.is_fraud, max(CASE WHEN c.complaint_id IS NOT NULL THEN 1 ELSE 0 END) complained, max(CASE WHEN c.subcategory='Cargo no reconocido' THEN 1 ELSE 0 END) unrecognized
  FROM transactions t LEFT JOIN complaints c ON c.customer_id=t.customer_id AND c.creation_date > t.transaction_date AND c.creation_date <= t.transaction_date + INTERVAL 30 DAY GROUP BY ALL)
SELECT is_fraud, count(*) n, round(avg(complained)*100,3) complaint_30d_pct, round(avg(unrecognized)*100,3) unrecognized_charge_30d_pct FROM x GROUP BY ALL;

-- [K4] repeat contact by first-contact resolution
WITH o AS (SELECT was_resolved, interaction_date, lead(interaction_date) OVER (PARTITION BY customer_id ORDER BY interaction_date) nxt FROM call_center_interactions)
SELECT was_resolved, count(*) n, round(avg(coalesce(nxt <= interaction_date + INTERVAL 7 DAY, false)::int)*100,2) repeat_7d_pct, round(avg(coalesce(nxt <= interaction_date + INTERVAL 30 DAY, false)::int)*100,2) repeat_30d_pct FROM o GROUP BY ALL;
