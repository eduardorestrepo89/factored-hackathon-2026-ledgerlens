# LATAM Bank data probes: contact-center operations, capacity gaps and complaint/digital patterns for AI-agent use cases

Source for every number below: read-only DuckDB 1.5.5 queries over the full populations in `datathon/analysis/bank.duckdb`, run on 2026-09-29. `[Px.y]` cites the query whose exact SQL is listed under **SQL used** in the same section. `[Fnn]` cites the team document `datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md`. All queries ran in under 6 s. No sampling.

Standing assumptions (labelled wherever they are used):
- **A1 (shift hours):** outside the PDFs (not opened), shift hours are not documented anywhere. Where needed I assume 8-hour bands: Morning 06–14, Afternoon 14–22, Night 22–06. Rotating agents are split 1/3 into each band.
- **A2 (annualisation):** the period is 1,097 business days (2023-06-17 → 2026-06-17), i.e. 3.0034 years. "Per year" = 3-year total / 3.0034. Calendar-year counts use `process_date`.
- **A3 (agent-hours):** `duration_seconds` is null for every chat and email contact (96,234 contacts, 14.0%). Agent-hours therefore cover phone and video only and are floors.
- **A4 (clock):** hour of day uses the raw `interaction_date` / `event_date` timestamp. Its time zone is unknown (DEC-9).

## 1. Capacity vs demand by hour: is there a night / after-hours coverage gap (all agents, Portuguese-capable, fraud specialists)?

### Takeaway
**AI-agent verdict:** a 24/7 AI tier or an AI-mediated Portuguese night handoff can be argued **from the roster only**, never from observed service. Under A1, the night band has half the agents of a day band (223 vs 433 incl. rotating) for the same demand (about 208 contacts/day per band). There are **0 dedicated Portuguese-capable fraud specialists at night** (0.33 if the single rotating one is split). But history shows no gap at all: waits, resolution and escalation are identical in every band, and every agent, whatever their shift, handles contacts at every hour. Any "after-hours" benefit is therefore a labelled projection.

### Cited Findings
**Demand is flat across the 24 hours, in every channel and country**
- Each clock hour holds 4.12–4.24% of the 686,296 contacts (28,270–29,081 per hour over 3 years) [P1.1].
- By band [P1.12]:

  | Band | Contacts | Inbound phone | Outbound phone | Chat (App/WhatsApp/Web Chat) | Email | Video |
  |---|---:|---:|---:|---:|---:|---:|
  | 06–14 | 228,673 | 159,902 | 34,513 | 22,821 | 9,195 | 2,242 |
  | 14–22 | 229,103 | 160,924 | 33,973 | 22,774 | 9,142 | 2,290 |
  | 22–06 | 228,520 | 159,852 | 34,086 | 23,096 | 9,206 | 2,280 |

- The night share (22–06) is 33.29–33.31% for Argentine, Colombian and Mexican customers [P1.17], and 33.3% on both weekdays and weekends [P1.8].
- Fraud-relevant demand is flat too:
  - fraud transactions by band: 1,501 / 1,388 / 1,427;
  - "Cargo no reconocido" complaints: 4,095 / 4,148 / 4,054;
  - Queja contacts: 39,040 / 39,116 / 38,865 [P1.13].
- Transactions (183,570–185,224 per clock hour), digital events (645,510–657,217 per hour) and complaints (2,676–2,890 per hour) are also uniform [P1.14], [P1.15]. This extends F4.
- **Night-band (22–06) demand per year** (A2): 76,087 contacts and 5,831 phone/video agent-hours.

  | Reason | Night contacts/yr | Night agent-hours/yr |
  |---|---:|---:|
  | Transaccional | 26,657 | 1,405 |
  | Producto | 16,660 | 1,059 |
  | Queja | 12,940 | 1,341 |
  | Técnico | 11,437 | 983 |
  | Comercial | 6,148 | 787 |
  | Retención | 2,245 | 256 |

  [P1.18]

**Supply (active roster, 1,090 of 1,200 agents) by `work_shift`** [P1.6]

| Shift | Active | Portuguese-capable | Fraudes | PT + Fraudes | Quejas y Reclamos | English |
|---|---:|---:|---:|---:|---:|---:|
| Morning | 373 | 41 | 31 | 4 | 17 | 153 |
| Afternoon | 373 | 36 | 30 | 2 | 20 | 159 |
| Night | 163 | 16 | 24 | **0** | 14 | 70 |
| Rotating | 181 | 22 | 11 | 1 | 13 | 61 |
| Total | 1,090 | 115 | 96 | 7 | 64 | 443 |

- This matches F7a and F42. The other agent statuses are Inactive (22), Leave (29) and Vacation (59) [P1.0].

**Load per band under A1** [P1.7]

| Band | Contacts/day | Handled h/day | Agents incl. 1/3 rotating | Contacts per agent-day | PT agents | Fraud agents | PT fraud agents |
|---|---:|---:|---:|---:|---:|---:|---:|
| Morning | 208.5 | 16.0 | 433.3 | 0.481 | 48.3 | 34.7 | 4.33 |
| Afternoon | 208.8 | 16.0 | 433.3 | 0.482 | 43.3 | 33.7 | 2.33 |
| Night | 208.3 | 16.0 | 223.3 | **0.933** | 23.3 | 27.7 | **0.33** |

- The night per-agent load is 1.94× the day load. Absolute load is tiny: about 2.0 agents busy at any moment, which is 0.46% (day) and 0.89% (night) utilisation even if every agent worked their band every day [P1.7].
- The volume is small relative to the roster: 625.6 contacts/day for 1,090 active agents (0.57 per agent per day).
- The agent field `total_monthly_interactions` (median 454/month; sum 451,168/month for active agents) implies 16.24M contacts over 36 months. The table holds 686,296, which is **4.23%** of that [P1.11]. Observed contacts per agent are about 17.5/month in every shift [P1.9].

**History ignores shifts entirely**
- Agents of every shift handle 33.2–33.6% of their contacts in each band [P1.3].
- All 373 Morning and all 373 Afternoon agents handled at least one 22–06 contact [P1.16].
- Portuguese-capable agents handle 33.12% of their contacts at night; others handle 33.32% [P1.10].
- `agent_type` does not constrain channel. For example, "In-Person" agents took 112,513 phone contacts, and "Phone" agents took 13,177 App chats [P1.5].
- Only currently Active agents appear on contacts (686,296/686,296) [P1.4].
- **No observed night penalty.** By band [P1.19]:
  - median inbound wait: 119 / 120 / 119 s (p90 196 s everywhere);
  - resolved: 76.53 / 76.70 / 76.72%;
  - escalated: 9.99 / 9.92 / 9.98%;
  - median handle time: 291 / 290 / 291 s.
- Portuguese demand is zero. Customers are México 74,907, Colombia 45,251 and Argentina 29,842 only [P2.7]; transcripts contain no Portuguese [F15, DEC-11].

#### SQL used
```sql
-- [P1.0]
SELECT agent_status, work_shift, agent_type, count(*) n FROM service_agents GROUP BY ALL ORDER BY 1,2,3;
-- [P1.1]
SELECT hour(interaction_date) h, count(*) total, count(*) FILTER (WHERE channel='Phone') phone, count(*) FILTER (WHERE channel='Email') email, round(100.0*count(*)/sum(count(*)) over(),2) pct FROM call_center_interactions GROUP BY 1 ORDER BY 1;
-- [P1.3]
SELECT a.work_shift, count(*) n,
 round(100.0*avg((hour(i.interaction_date) BETWEEN 6 AND 13)::int),2) pct_06_14,
 round(100.0*avg((hour(i.interaction_date) BETWEEN 14 AND 21)::int),2) pct_14_22,
 round(100.0*avg((hour(i.interaction_date) >= 22 OR hour(i.interaction_date) < 6)::int),2) pct_22_06
FROM call_center_interactions i JOIN service_agents a USING(agent_id) GROUP BY 1 ORDER BY 1;
-- [P1.4]
SELECT coalesce(a.agent_status,'(no agent/orphan)') agent_status, count(*) n FROM call_center_interactions i LEFT JOIN service_agents a USING(agent_id) GROUP BY 1;
-- [P1.5]
SELECT a.agent_type, i.channel, count(*) n FROM call_center_interactions i JOIN service_agents a USING(agent_id) GROUP BY ALL ORDER BY 1, n DESC;
-- [P1.6]
SELECT work_shift, count(*) active_all, count(*) FILTER (WHERE languages LIKE '%portugu%') active_pt, count(*) FILTER (WHERE specialty='Fraudes') active_fraud, count(*) FILTER (WHERE specialty='Fraudes' AND languages LIKE '%portugu%') active_pt_fraud, count(*) FILTER (WHERE specialty='Quejas y Reclamos') active_quejas, count(*) FILTER (WHERE languages LIKE '%ingl%') active_en FROM service_agents WHERE agent_status='Active' GROUP BY ROLLUP(1) ORDER BY 1;
-- [P1.7]  (A1 bands; rotating split 1/3)
WITH d AS (SELECT count(DISTINCT process_date) nd FROM call_center_interactions),
c AS (SELECT CASE WHEN hour(interaction_date) BETWEEN 6 AND 13 THEN 'Morning' WHEN hour(interaction_date) BETWEEN 14 AND 21 THEN 'Afternoon' ELSE 'Night' END band, count(*) n, sum(duration_seconds)/3600.0 hrs FROM call_center_interactions GROUP BY 1),
a AS (SELECT work_shift, count(*) ag, count(*) FILTER (WHERE languages LIKE '%portugu%') pt, count(*) FILTER (WHERE specialty='Fraudes') fr, count(*) FILTER (WHERE specialty='Fraudes' AND languages LIKE '%portugu%') ptfr, count(*) FILTER (WHERE specialty='Quejas y Reclamos') qr FROM service_agents WHERE agent_status='Active' GROUP BY 1),
r AS (SELECT ag rag, pt rpt, fr rfr, ptfr rptfr, qr rqr FROM a WHERE work_shift='Rotating')
SELECT c.band, c.n contacts_3y, round(c.n / d.nd,1) contacts_per_day, round(c.hrs/d.nd,1) handled_hours_per_day, round(c.hrs/d.nd/8,2) avg_concurrent_busy_agents,
 a.ag dedicated_agents, round(a.ag + rag/3.0,1) agents_incl_rot, round(c.n/d.nd/(a.ag + rag/3.0),3) contacts_per_agent_day, round(100*c.hrs/d.nd/((a.ag + rag/3.0)*8),2) utilisation_pct_if_all_on_shift,
 a.pt pt, round(a.pt + rpt/3.0,1) pt_incl_rot, a.fr fraud, round(a.fr + rfr/3.0,1) fraud_incl_rot, a.ptfr pt_fraud, round(a.ptfr + rptfr/3.0,2) pt_fraud_incl_rot, a.qr quejas, round(a.qr+rqr/3.0,1) quejas_incl_rot
FROM c, d, r, a WHERE a.work_shift = c.band ORDER BY c.band;
-- [P1.8]
SELECT (isodow(process_date) >= 6) weekend, round(100.0*avg((hour(interaction_date) >= 22 OR hour(interaction_date) < 6)::int),2) pct_night, count(*) n FROM call_center_interactions GROUP BY 1;
-- [P1.9]
WITH o AS (SELECT agent_id, count(*) n FROM call_center_interactions GROUP BY 1)
SELECT a.work_shift, count(*) agents, round(avg(o.n)) avg_contacts_3y, round(avg(o.n)/36.0,1) avg_contacts_per_month_observed, round(avg(a.total_monthly_interactions),1) avg_field FROM service_agents a LEFT JOIN o USING(agent_id) GROUP BY 1 ORDER BY 1;
-- [P1.10]
SELECT (a.languages LIKE '%portugu%') pt_capable, count(*) n, round(100.0*avg((hour(i.interaction_date) >= 22 OR hour(i.interaction_date) < 6)::int),2) pct_22_06 FROM call_center_interactions i JOIN service_agents a USING(agent_id) GROUP BY 1;
-- [P1.11]
SELECT round(sum(total_monthly_interactions)) field_sum_per_month_active, round(sum(total_monthly_interactions)*36) implied_3y, (SELECT count(*) FROM call_center_interactions) observed_3y, round((SELECT count(*) FROM call_center_interactions)*100.0/(sum(total_monthly_interactions)*36),2) observed_pct_of_implied, min(total_monthly_interactions) mn, median(total_monthly_interactions) med, max(total_monthly_interactions) mx FROM service_agents WHERE agent_status='Active';
-- [P1.12]
SELECT CASE WHEN hour(interaction_date) BETWEEN 6 AND 13 THEN '1 06-14' WHEN hour(interaction_date) BETWEEN 14 AND 21 THEN '2 14-22' ELSE '3 22-06' END band,
 count(*) FILTER (WHERE interaction_type='Inbound Call') phone_in, count(*) FILTER (WHERE interaction_type='Outbound Call') phone_out, count(*) FILTER (WHERE interaction_type='Chat') chat, count(*) FILTER (WHERE channel='WhatsApp') whatsapp, count(*) FILTER (WHERE interaction_type='Email') email, count(*) FILTER (WHERE interaction_type='Video') video, count(*) total FROM call_center_interactions GROUP BY 1 ORDER BY 1;
-- [P1.13]
SELECT band, sum(fraud_tx) fraud_tx, sum(unrec_cmp) unrecognized_charge_complaints, sum(queja) queja_contacts FROM (
 SELECT CASE WHEN hour(transaction_date) BETWEEN 6 AND 13 THEN '1 06-14' WHEN hour(transaction_date) BETWEEN 14 AND 21 THEN '2 14-22' ELSE '3 22-06' END band, count(*) FILTER (WHERE is_fraud) fraud_tx, 0 unrec_cmp, 0 queja FROM transactions GROUP BY 1
 UNION ALL SELECT CASE WHEN hour(creation_date) BETWEEN 6 AND 13 THEN '1 06-14' WHEN hour(creation_date) BETWEEN 14 AND 21 THEN '2 14-22' ELSE '3 22-06' END, 0, count(*) FILTER (WHERE subcategory='Cargo no reconocido'), 0 FROM complaints GROUP BY 1
 UNION ALL SELECT CASE WHEN hour(interaction_date) BETWEEN 6 AND 13 THEN '1 06-14' WHEN hour(interaction_date) BETWEEN 14 AND 21 THEN '2 14-22' ELSE '3 22-06' END, 0, 0, count(*) FILTER (WHERE contact_reason='Queja') FROM call_center_interactions GROUP BY 1) GROUP BY 1 ORDER BY 1;
-- [P1.14]
SELECT h, sum(tx) tx, sum(de) digital_events FROM (SELECT hour(transaction_date) h, count(*) tx, 0 de FROM transactions GROUP BY 1 UNION ALL SELECT hour(event_date), 0, count(*) FROM digital_events GROUP BY 1) GROUP BY 1 ORDER BY 1;
-- [P1.15]
SELECT hour(creation_date) h, count(*) n FROM complaints GROUP BY 1 ORDER BY 1;
-- [P1.16]
SELECT a.work_shift, count(DISTINCT i.agent_id) FILTER (WHERE hour(i.interaction_date) >= 22 OR hour(i.interaction_date) < 6) agents_handling_night_contacts, count(DISTINCT i.agent_id) agents FROM call_center_interactions i JOIN service_agents a USING(agent_id) GROUP BY 1 ORDER BY 1;
-- [P1.17]
SELECT c.country, round(100.0*avg((hour(i.interaction_date) >= 22 OR hour(i.interaction_date) < 6)::int),2) pct_22_06, count(*) n FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY 1;
-- [P1.18]
SELECT contact_reason, count(*) FILTER (WHERE hour(interaction_date) >= 22 OR hour(interaction_date) < 6) night_3y, round(count(*) FILTER (WHERE hour(interaction_date) >= 22 OR hour(interaction_date) < 6)/(1097/365.25)) night_per_year, round(sum(duration_seconds) FILTER (WHERE hour(interaction_date) >= 22 OR hour(interaction_date) < 6)/3600/(1097/365.25)) night_hrs_per_year FROM call_center_interactions GROUP BY ROLLUP(1) ORDER BY 1;
-- [P1.19]
SELECT CASE WHEN hour(interaction_date) BETWEEN 6 AND 13 THEN '1 06-14' WHEN hour(interaction_date) BETWEEN 14 AND 21 THEN '2 14-22' ELSE '3 22-06' END band, count(*) n, median(wait_time_seconds) med_wait_s, round(quantile_cont(wait_time_seconds,0.9)) p90_wait_s, round(100*avg(was_resolved::int),2) res_pct, round(100*avg(was_escalated::int),2) esc_pct, median(duration_seconds) med_handle_s FROM call_center_interactions GROUP BY 1 ORDER BY 1;
```

### Inferences
- The only defensible "coverage gap" is a **roster fact**:
  - the night shift has 163 dedicated agents vs 373 for each day shift;
  - there is no dedicated Portuguese fraud specialist at night [P1.6];
  - under A1 that is ~1.9× the per-agent night load.
  
  It is **not** an observed service gap, because the generator routes contacts to agents regardless of shift [P1.3], [P1.16], and outcomes are identical by band [P1.19]. (Medium confidence: this depends on A1.)
- Recorded agent time (about 16 handled hours/day per band) is a tiny fraction of the roster. With 4.23% of the documented per-agent volume [P1.11], the interactions table is probably a sample or is unrelated to the `total_monthly_interactions` field (inference). So no "capacity shortfall" in hours can be claimed from this data.
- For a 24/7 AI tier, the honest framing is:
  - about 76K contacts/yr (a third of the total) arrive 22–06 by raw clock [P1.18];
  - the scheduled roster at night is half the day roster [P1.6];
  - the benefit is projected, not measured.
- For the DEC-5a Portuguese handoff, the night fallback (Spanish fraud queue plus a Portuguese summary or AI translation) is directly supported by 24 non-Portuguese night fraud specialists and 0 Portuguese ones [P1.6], [P2.5].

### Gaps
- Real shift hours are undocumented outside the PDFs, which I did not open. All band figures depend on A1.
- There is no abandonment, queue-length or service-level field, so an after-hours service gap cannot be measured, only asserted from the roster.
- The time zone of raw timestamps is unknown (DEC-9). "Night" may not be local night for all three countries.

## 2. Agent languages × specialty × shift × country of origin: who could serve a Portuguese customer only with AI translation?

### Takeaway
**AI-agent verdict:** AI-mediated translation is the one Portuguese-capacity lever the roster supports. **975 of 1,090 active agents (89.4%) could serve a Portuguese speaker only through translation.** That includes 89 of 96 fraud specialists and all 24 night fraud specialists, and 57 of 64 complaint specialists. But Portuguese demand in the data is zero (DEC-11), so this is a capacity argument, not a demand one.

### Cited Findings
**Languages (active):**
- español 587;
- español + inglés 388;
- español + portugués 60;
- español + inglés + portugués 55 [F7a].

**Country of origin (active):** Mexico 552, Colombia 327, Argentina 211. `native_accent` maps 1:1 to country of origin [P2.0], [P2.8].

**Experience (active):** Specialist 696, Senior 252, Mid-Senior 126, Junior 16. Night: 103 Specialist, 41 Senior, 16 Mid-Senior, 3 Junior [P2.0], [P2.9].

**Active agents by specialty × languages × shift** [P2.1]. This is the 3-way marginal of the 4-way table; the 4-way has 267 non-empty cells, max 43 agents, 1,090 in total [P2.6].

| Specialty | Languages | Morning | Afternoon | Night | Rotating | Total |
|---|---|---:|---:|---:|---:|---:|
| (generalist, null) | es | 88 | 74 | 37 | 44 | 243 |
| (generalist) | es, en | 50 | 63 | 22 | 18 | 153 |
| (generalist) | es, en, pt | 12 | 2 | 5 | 4 | 23 |
| (generalist) | es, pt | 4 | 11 | 4 | 4 | 23 |
| Cobranza | es / es,en / es,en,pt / es,pt | 19/9/2/2 | 16/14/2/1 | 4/6/1/0 | 6/2/0/2 | 45/31/5/5 |
| Créditos | es / es,en / es,en,pt / es,pt | 12/8/2/1 | 17/8/3/3 | 6/3/0/0 | 10/5/0/2 | 45/24/5/6 |
| **Fraudes** | es / es,en / es,en,pt / es,pt | 17/10/1/3 | 15/13/0/2 | **16/8/0/0** | 8/2/1/0 | 56/33/2/5 |
| Inversiones | es / es,en / es,en,pt / es,pt | 13/8/1/2 | 13/9/1/1 | 6/4/0/2 | 10/3/0/1 | 42/24/2/6 |
| **Quejas y Reclamos** | es / es,en / es,en,pt / es,pt | 8/7/2/0 | 12/7/0/1 | 3/10/1/0 | 4/6/3/0 | 27/30/6/1 |
| Retención | es / es,en / es,en,pt / es,pt | 15/13/2/2 | 15/10/2/5 | 4/2/0/2 | 10/3/0/0 | 44/28/4/9 |
| Soporte Técnico | es / es,en / es,en,pt / es,pt | 14/10/4/0 | 17/14/0/1 | 5/4/0/0 | 11/5/2/2 | 47/33/6/3 |
| Ventas | es / es,en / es,en,pt / es,pt | 19/12/0/1 | 10/10/1/0 | 3/4/0/1 | 6/6/1/0 | 38/32/2/2 |

**Active agents by country of origin × languages × shift** [P2.2]

| Country | Languages | Morning | Afternoon | Night | Rotating | Total |
|---|---|---:|---:|---:|---:|---:|
| Argentina | es / es,en / es,en,pt / es,pt | 47/29/6/1 | 37/18/5/4 | 13/10/0/1 | 19/12/5/4 | 116/69/16/10 |
| Colombia | es / es,en / es,en,pt / es,pt | 55/36/9/6 | 55/40/3/6 | 23/22/1/3 | 42/20/2/4 | 175/118/15/19 |
| Mexico | es / es,en / es,en,pt / es,pt | 103/62/11/8 | 97/90/3/15 | 48/31/6/5 | 48/18/4/3 | 296/201/24/31 |

**AI-translation pool: active agents without Portuguese** [P2.5]

| Specialty | Morning | Afternoon | Night | Rotating | Non-PT total | PT-capable | PT at night |
|---|---:|---:|---:|---:|---:|---:|---:|
| (generalist) | 138 | 137 | 59 | 62 | 396 | 46 | 9 |
| Cobranza | 28 | 30 | 10 | 8 | 76 | 10 | 1 |
| Créditos | 20 | 25 | 9 | 15 | 69 | 11 | 0 |
| Fraudes | 27 | 28 | 24 | 10 | 89 | 7 | **0** |
| Inversiones | 21 | 22 | 10 | 13 | 66 | 8 | 2 |
| Quejas y Reclamos | 15 | 19 | 13 | 10 | 57 | 7 | 1 |
| Retención | 28 | 25 | 6 | 13 | 72 | 13 | 2 |
| Soporte Técnico | 24 | 31 | 9 | 16 | 80 | 9 | 0 |
| Ventas | 31 | 20 | 7 | 12 | 70 | 4 | 1 |
| **Total** | 332 | 337 | 147 | 159 | **975** | **115** | **16** |

**The 7 Portuguese-capable fraud specialists** [P2.4]
- Morning (4): Colombia Hybrid, Colombia Phone, Mexico Digital, Mexico In-Person.
- Afternoon (2): Mexico Phone ×2.
- Rotating (1): Mexico Phone.

**The 7 Portuguese-capable complaint specialists** [P2.4]
- Morning (2): Argentina Digital, Colombia Hybrid.
- Afternoon (1): Mexico Phone.
- Night (1): Mexico Digital.
- Rotating (3): Argentina Phone, Colombia Hybrid, Mexico In-Person.

This matches F42.

**Routing ignores country.** Every customer country gets 50.7–50.8% Mexican, 29.8–30.0% Colombian and 19.2–19.5% Argentine agents. That is the pool share (50.6 / 30.0 / 19.4%) [P3.10], consistent with F6 and F41.

#### SQL used
```sql
-- [P2.0]
SELECT 'country_of_origin' f, country_of_origin v, count(*) n, count(*) FILTER (WHERE agent_status='Active') active FROM service_agents GROUP BY ALL
UNION ALL SELECT 'native_accent', native_accent, count(*), count(*) FILTER (WHERE agent_status='Active') FROM service_agents GROUP BY ALL
UNION ALL SELECT 'experience_level', experience_level, count(*), count(*) FILTER (WHERE agent_status='Active') FROM service_agents GROUP BY ALL ORDER BY 1, 3 DESC;
-- [P2.1]
SELECT coalesce(specialty,'(generalist/null)') specialty, languages, count(*) FILTER (WHERE work_shift='Morning') morning, count(*) FILTER (WHERE work_shift='Afternoon') afternoon, count(*) FILTER (WHERE work_shift='Night') night, count(*) FILTER (WHERE work_shift='Rotating') rotating, count(*) total FROM service_agents WHERE agent_status='Active' GROUP BY ALL ORDER BY 1, 2;
-- [P2.2]
SELECT country_of_origin, languages, count(*) FILTER (WHERE work_shift='Morning') morning, count(*) FILTER (WHERE work_shift='Afternoon') afternoon, count(*) FILTER (WHERE work_shift='Night') night, count(*) FILTER (WHERE work_shift='Rotating') rotating, count(*) total FROM service_agents WHERE agent_status='Active' GROUP BY ALL ORDER BY 1, 2;
-- [P2.4]
SELECT coalesce(specialty,'(generalist/null)') specialty, work_shift, country_of_origin, languages, agent_type, count(*) n FROM service_agents WHERE agent_status='Active' AND languages LIKE '%portugu%' GROUP BY ALL ORDER BY 1,2,3;
-- [P2.5]
SELECT coalesce(specialty,'(generalist/null)') specialty, count(*) FILTER (WHERE languages NOT LIKE '%portugu%' AND work_shift='Morning') morning, count(*) FILTER (WHERE languages NOT LIKE '%portugu%' AND work_shift='Afternoon') afternoon, count(*) FILTER (WHERE languages NOT LIKE '%portugu%' AND work_shift='Night') night, count(*) FILTER (WHERE languages NOT LIKE '%portugu%' AND work_shift='Rotating') rotating, count(*) FILTER (WHERE languages NOT LIKE '%portugu%') total_non_pt, count(*) FILTER (WHERE languages LIKE '%portugu%') pt_capable, count(*) FILTER (WHERE languages LIKE '%portugu%' AND work_shift='Night') pt_night, count(*) all_active FROM service_agents WHERE agent_status='Active' GROUP BY ROLLUP(1) ORDER BY 1;
-- [P2.6]  (full 4-way table; drop the outer SELECT to list all 267 cells)
SELECT count(*) nonempty_cells, sum(n) agents, max(n) max_cell FROM (SELECT languages, specialty, work_shift, country_of_origin, count(*) n FROM service_agents WHERE agent_status='Active' GROUP BY ALL);
-- [P2.7]
SELECT country, detected_accent, count(*) n FROM customers GROUP BY ALL ORDER BY 1, n DESC;
-- [P2.8]
SELECT country_of_origin, native_accent, count(*) n FROM service_agents WHERE agent_status='Active' GROUP BY ALL ORDER BY 1, n DESC;
-- [P2.9]
SELECT work_shift, count(*) FILTER (WHERE experience_level='Junior') junior, count(*) FILTER (WHERE experience_level='Mid-Senior') mid_senior, count(*) FILTER (WHERE experience_level='Senior') senior, count(*) FILTER (WHERE experience_level='Specialist') specialist FROM service_agents WHERE agent_status='Active' GROUP BY 1 ORDER BY 1;
-- [P3.10]
SELECT customer_country, agent_country, n, round(100.0*n/sum(n) over(partition by customer_country),1) pct FROM (SELECT c.country customer_country, a.country_of_origin agent_country, count(*) n FROM call_center_interactions i JOIN customers c USING(customer_id) JOIN service_agents a USING(agent_id) GROUP BY ALL) ORDER BY 1, n DESC;
```

### Inferences
- With AI translation, the Portuguese fraud pool grows from 7 to 96 active agents, and at night from 0 to 24 dedicated agents (plus rotating) [P2.5]. For DEC-5a, the constraint shifts from "who speaks Portuguese" to "is a fraud specialist on shift".
- Mexico is 50.6% of agents and 49.9% of customers, but routing is random [P3.10]. An accent- or country-matching feature has no historical outcome effect to exploit (F6).
- The roster is almost entirely "Specialist"/"Senior" (948/1,090). Experience cannot be used to justify AI copilots for juniors: there are only 16 active juniors [P2.0].

### Gaps
- The full 4-way table (267 cells) is not reproduced here. The SQL [P2.6] regenerates it, and all its 3-way marginals are shown.
- There is no proficiency level for languages and no data on translation quality or on how long a translated interaction takes. Any translation overhead is an assumption.

## 3. Cost of demand: handle time, escalation and follow-up by reason × channel × country × segment; agent-hours per year; costliest low-resolution cells

### Takeaway
**AI-agent verdict:** the two grounded targets are:
- **Queja, inbound phone:** the costliest low-resolution cell (3,310 agent-h/yr, 43.7% resolved, 62.8% follow-up, 1,873 "unresolved" agent-h/yr). It fits structured complaint intake and summarisation to cut human handle time.
- **Transaccional:** the largest pool (79.9K contacts and 4,216 h/yr, 91.5% resolved). It fits automated resolution.

Country and segment add no signal, because every cell is the reason's profile scaled by customer count. All hour figures are floors, because chat and email have no handle time (A3).

### Cited Findings
**Handle time is recorded only for phone and video**
- 96,234 contacts (14.0%) have null duration and null wait: all 27,543 emails and all 68,691 chats [P3.0], [P3.11].
- Outbound calls and video have no wait time. Inbound median wait is 119 s [P3.0].
- Phone and video medians are 289–293 s in every channel [P3.0].

**Per reason, per year** (A2) [P3.2]

| Reason | Contacts (3y) | Contacts/yr | Agent-h (3y) | **Agent-h/yr** | Median s | Resolved | Escalated | Follow-up | Outbound |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Transaccional | 240,056 | 79,927 | 12,663 | **4,216** | 205 | 91.5% | 9.9% | 22.1% | 15.0% |
| Queja | 117,021 | 38,963 | 12,160 | **4,049** | 431 | 43.6% | 10.0% | 63.0% | 14.8% |
| Producto | 150,863 | 50,230 | 9,593 | 3,194 | 263 | 89.6% | 10.0% | 23.8% | 15.0% |
| Técnico | 102,899 | 34,261 | 8,861 | 2,950 | 360 | 69.9% | 10.1% | 40.6% | 15.0% |
| Comercial | 54,879 | 18,272 | 7,061 | 2,351 | 540 | 65.2% | 9.8% | 44.5% | 15.0% |
| Retención | 20,578 | 6,852 | 2,350 | 782 | 478 | 60.2% | 9.8% | 49.1% | 14.7% |
| **All** | 686,296 | 228,505 | 52,688 | **17,543** | 291 | 76.6% | 10.0% | 34.8% | 14.9% |

- This extends F45 and F3.
- Volume is stable by year: 228,210 contacts in 2024 and 229,056 in 2025 [P3.9].

**Top reason × channel cells by unresolved agent-hours/yr** (hours × (1 − resolved)) [P3.7]

| Reason | Channel | Contacts (3y) | Agent-h/yr | Resolved | Unresolved agent-h/yr |
|---|---|---:|---:|---:|---:|
| Queja | Inbound call | 82,261 | 3,310 | 43.7% | **1,873** |
| Técnico | Inbound call | 71,974 | 2,398 | 69.9% | 720 |
| Comercial | Inbound call | 38,338 | 1,914 | 65.0% | 669 |
| Queja | Outbound call | 17,293 | 692 | 43.1% | 395 |
| Transaccional | Inbound call | 168,074 | 3,431 | 91.5% | 350 |
| Producto | Inbound call | 105,610 | 2,603 | 89.6% | 266 |
| Retención | Inbound call | 14,421 | 640 | 60.5% | 253 |

**Inbound and outbound are the same workload.** Per reason, outbound has the same median handle time (e.g. Queja 429 vs 432 s), resolution (43.1 vs 43.7%), escalation and follow-up as inbound [P3.3]. Outbound is 14.7–15.0% of every reason [P3.2].

**Country × segment (72 cells)** [P3.4], [P3.5]
- Within each reason, resolved spans a narrow band:
  - Transaccional 90.9–91.9%;
  - Queja 42.9–45.4%;
  - Producto 88.9–90.5%;
  - Técnico 69.3–70.4%;
  - Comercial 61.2–66.6%;
  - Retención 53.3–64.4% (smallest cell n = 212).
- Median handle time varies by at most 26 s within a reason.
- Escalation is 6.0–12.3% in every cell.
- Agent-h/yr by country: México 8,770, Colombia 5,289, Argentina 3,484. By segment: Basic 10,515, Plus 4,397, Premium 1,757, Student 874 [P3.6].

**Handle time vs outcome.** For most reasons, resolved and unresolved contacts have the same p10/p50/p90 duration. Transaccional is the exception: unresolved p50 234 s and p90 461 s vs resolved 203 s and 323 s. That is the one non-flat duration pattern [P3.8].

#### SQL used
```sql
-- [P3.0]
SELECT channel, interaction_type, count(*) n, count(duration_seconds) with_duration, count(wait_time_seconds) with_wait, median(duration_seconds) med_dur_s, round(avg(duration_seconds)) mean_dur_s, min(duration_seconds) min_s, max(duration_seconds) max_s, median(wait_time_seconds) med_wait_s FROM call_center_interactions GROUP BY ALL ORDER BY n DESC;
-- [P3.1]
SELECT contact_reason, CASE WHEN interaction_type IN ('Inbound Call','Outbound Call') THEN interaction_type ELSE interaction_type || ' (' || channel || ')' END chan, count(*) n, round(sum(duration_seconds)/3600) hrs_3y, round(sum(duration_seconds)/3600/(1097/365.25)) hrs_per_year, median(duration_seconds) med_s,
 round(100*avg(was_resolved::int),1) resolved_pct, round(100*avg(was_escalated::int),1) esc_pct, round(100*avg(requires_followup::int),1) followup_pct, round(sum(duration_seconds*(1-was_resolved::int))/3600/(1097/365.25)) unresolved_hrs_per_year
FROM call_center_interactions GROUP BY ALL ORDER BY hrs_3y DESC;
-- [P3.2]
SELECT contact_reason, count(*) n, round(count(*)/(1097/365.25)) contacts_per_year, round(sum(duration_seconds)/3600) hrs_3y, round(sum(duration_seconds)/3600/(1097/365.25)) hrs_per_year, round(avg(duration_seconds)) mean_s, median(duration_seconds) med_s, round(100*avg(was_resolved::int),1) resolved_pct, round(100*avg(was_escalated::int),1) esc_pct, round(100*avg(requires_followup::int),1) followup_pct, round(100*avg((interaction_type='Outbound Call')::int),1) outbound_pct FROM call_center_interactions GROUP BY ROLLUP(1) ORDER BY hrs_3y DESC;
-- [P3.3]
SELECT interaction_type, contact_reason, count(*) n, round(sum(duration_seconds)/3600) hrs_3y, median(duration_seconds) med_s, round(100*avg(was_resolved::int),1) resolved_pct, round(100*avg(was_escalated::int),1) esc_pct, round(100*avg(requires_followup::int),1) followup_pct FROM call_center_interactions WHERE channel='Phone' GROUP BY ALL ORDER BY 1, n DESC;
-- [P3.4]
SELECT i.contact_reason, c.country, c.segment, count(*) n, round(sum(i.duration_seconds)/3600) hrs_3y, median(i.duration_seconds) med_s, round(100*avg(i.was_resolved::int),1) resolved_pct, round(100*avg(i.was_escalated::int),1) esc_pct, round(100*avg(i.requires_followup::int),1) fu_pct FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY ALL ORDER BY 1,2,3;
-- [P3.5]
WITH x AS (SELECT i.contact_reason, c.country, c.segment, count(*) n, median(i.duration_seconds) med_s, avg(i.was_resolved::int) r, avg(i.was_escalated::int) e FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY ALL)
SELECT contact_reason, count(*) cells, min(n) min_n, round(100*min(r),1) min_res, round(100*max(r),1) max_res, min(med_s) min_med_s, max(med_s) max_med_s, round(100*min(e),1) min_esc, round(100*max(e),1) max_esc FROM x GROUP BY 1 ORDER BY 1;
-- [P3.6]
SELECT c.country, c.segment, count(*) n, round(sum(i.duration_seconds)/3600/(1097/365.25)) hrs_per_year FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY ROLLUP(1,2) ORDER BY 1,2;
-- [P3.7]
SELECT contact_reason, channel, interaction_type, count(*) n, round(sum(duration_seconds)/3600/(1097/365.25)) hrs_per_year, round(100*avg(was_resolved::int),1) resolved_pct, round(sum(duration_seconds*(1-was_resolved::int))/3600/(1097/365.25)) unresolved_hrs_per_year FROM call_center_interactions GROUP BY ALL ORDER BY unresolved_hrs_per_year DESC LIMIT 12;
-- [P3.8]
SELECT contact_reason, was_resolved, was_escalated, count(*) n, quantile_cont(duration_seconds,0.1) p10, median(duration_seconds) p50, quantile_cont(duration_seconds,0.9) p90 FROM call_center_interactions GROUP BY ALL ORDER BY 1,2,3;
-- [P3.9]
SELECT year(process_date) y, count(DISTINCT process_date) n_days, count(*) n, round(sum(duration_seconds)/3600) hrs, count(*) FILTER (WHERE contact_reason='Queja') queja, count(*) FILTER (WHERE contact_reason='Retención') retencion FROM call_center_interactions GROUP BY 1 ORDER BY 1;
-- [P3.11]
SELECT count(*) n, count(*) FILTER (WHERE duration_seconds IS NULL) no_duration, round(100.0*count(*) FILTER (WHERE duration_seconds IS NULL)/count(*),1) pct_no_duration FROM call_center_interactions;
```

### Inferences
- "Unresolved agent-hours" is a sizing heuristic built on `was_resolved`, which is not verified first-contact resolution (FCR) (F3, [K4]). Use it for ranking, not as a savings claim.
- Queja is about 4,049 phone/video agent-h/yr at 431 s median. An agent that produces a structured handoff (DEC-5a) addresses the cell where human time is longest and resolution lowest, and it is grounded without assuming deflection.
- Transaccional (4,216 h/yr at 91.5% resolved) remains the pool for safe automated resolution (BO-1). The in-scope share is still an assumption (F45, DEC-0).
- Outbound (~15% of every reason) is not a separate proactive workflow in the data; it replicates the inbound profile [P3.3].
- Country and segment breakdowns are needed for reporting (brief) but carry no prioritisation signal (F37).

### Gaps
- Agent-hours for chat and email (14.0% of contacts) are unknown. The totals are floors.
- There is no cost-per-hour or salary data, so money figures would need an external assumption.
- `requires_followup` has no linked follow-up record, and unresolved contacts do not drive repeats [K4]. The "follow-up" cost cannot be quantified.

## 4. Complaints (PQR): taxonomy, regulator channel, amounts, compensation, resolution time, and which fields are not random

### Takeaway
**AI-agent verdict:** a regulator-aware complaint-intake agent can be grounded on:
- the taxonomy (4 case types × 5 categories × 6 reception channels);
- about **239 regulator complaints/yr** (México 119, Colombia 75, Argentina 44);
- the lifecycle rules: compensation, resolution text and resolution days exist only on Resolved/Closed; claimed amounts exist only on Claim/Complaint.

It can **not** be grounded on any priority, SLA, compensation-amount or resolution-time model. Compensation is independent of claimed amount and category, and resolution days are uniform 1–30 regardless of priority, SLA flag or channel.

### Cited Findings
**Volume**
- 67,095 complaints: 22,340/yr in total, México 11,112, Colombia 6,787, Argentina 4,440 [P4.15].
- "Cargo no reconocido": 4,094/yr (México 2,047, Colombia 1,241, Argentina 806) [P4.15], F7.

**case_type** (English enums): Complaint 40,452 (60.3%), Claim 16,598 (24.7%), Request 6,761 (10.1%), Suggestion 3,284 (4.9%) [P4.13].
- case_type × category is proportional; each category is about 20% within every case type [P4.22].

**category × subcategory.** Each of 5 categories has 13,194–13,580 rows: one subcategory plus about 1.3K null subcategory each (F7, [P4.2]):
- Branch: Atención en sucursal 11,892;
- Fees: Cobro indebido 12,194;
- Service: Calidad de servicio 11,886;
- Technical: Problema con app 12,128;
- Transactions: Cargo no reconocido 12,297.

**reception_channel** [P4.3]

| Channel | Total | Share | México | Colombia | Argentina |
|---|---:|---:|---:|---:|---:|
| Call Center | 33,761 | 50.3% | 16,774 | 10,278 | 6,709 |
| Email | 13,323 | 19.9% | 6,791 | 3,921 | 2,611 |
| Web | 9,884 | 14.7% | 4,868 | 3,030 | 1,986 |
| App | 6,727 | 10.0% | 3,297 | 2,103 | 1,327 |
| Branch | 2,683 | 4.0% | 1,287 | 826 | 570 |
| **Regulator** | **717** | **1.07%** | 358 | 226 | 133 |

- case_type × channel is proportional to the marginals. Regulator is 171 Claim, 435 Complaint, 69 Request and 42 Suggestion [P4.1].

**Regulator-channel complaints per year per country** [P4.21]

| Country | 3y | Per year (A2) | 2024 | 2025 | Of which "Cargo no reconocido" (3y) |
|---|---:|---:|---:|---:|---:|
| México | 358 | 119.2 | 113 | 124 | 72 |
| Colombia | 226 | 75.2 | 75 | 87 | 38 |
| Argentina | 133 | 44.3 | 39 | 42 | 28 |
| Total | 717 | 238.7 | 227 | 253 | 138 |

- Regulator complaints get no special treatment. Their category mix is 18.1–21.8% each, Resolved/Closed 23.1–28.9% (vs 23.8–24.5% for the rest), High/Critical 18.5–23.2% (n = 130–156 per category) [P4.20]. SLA breach is 22.5% vs about 20% [P4.13].

**claimed_amount**
- Present on 21,751 (32.4%) complaints. Range 50.27–4,999.93 [P4.23].
- It is present only on Claim (38.3%) and Complaint (38.1%). **Request and Suggestion: 0%** [P4.13].
- The distribution is identical in every category × currency cell: median about 2,300–2,760, p10 about 430–630, p90 about 4,400–4,600 [P4.5]. So the same nominal range is used for ARS, COP, MXN and USD (F40 caveat: the amount ignores currency).
- `currency` is present on 20,711 of the 21,751 amounts. There are 1,065 currencies without an amount [P4.6], [P4.23].

**compensation_granted**
- Present on 4,641 (6.9%), always > 0. Range 10.15–499.98; q1 127.7, median 252.6, q3 374.1, consistent with uniform 10–500 [P4.18].
- Present only on Resolved (3,874 of 13,512) and Closed (767 of 2,609) complaints. There are 0 on Open, In Process, Escalated or Rejected [P4.8].
- 28.8% of Resolved/Closed complaints get compensation, regardless of:
  - whether an amount was claimed: 28.0% with a claim vs 29.1% without; 3,188 compensations have no claimed amount [P4.18];
  - category × case_type: 24.5–32.9% [P4.19].
- It does not relate to claimed_amount: corr = 0.031 overall (−0.034 to 0.098 by category). The median comp/claim ratio is 0.099. Buckets: <50% of the claim 1,309, 50–99% 82, >100% 62 [P4.7], [P4.10].

**Resolution text**
- 15,310 (22.8%) complaints carry one of 5 templates. The text is present only on Resolved (12,833) and Closed (2,477) [P4.8], [P4.9], F17.
- The template "Se otorgó compensación al cliente…" carries compensation on only 845 of 3,034 (27.9%), the same rate as the other templates [P4.9].
- Descriptions are 1 template per category: "Queja relacionada con {category}" [P4.17].

**resolution_days**
- Present on 15,363 (22.9%): the Resolved/Closed rows. Range 1–30; p10 4, median 16, p90 28, mean 15.6. Histogram: 0–5 days 2,546; 6–15 days 5,073; 16–30 days 7,744, i.e. uniform [P4.11], [P4.12].
- It is identical by priority (Critical median 15, Low 16), case type, and channel (Regulator median 16).
- `sla_breached = true` has a median of 15 days vs 16 for false. SLA breach is not consistent with resolution time [P4.11]; extends F39.

**resolution_satisfaction** is present only on Closed complaints (2,484), mean 3.0–3.1. It is unrelated to compensation or speed (2.95–3.09 across cells) [P4.8], [P4.14].

**Assignment is random over the roster.** 43,980 complaints are assigned:
- generalists 39.5% (roster share 40.6%);
- Quejas y Reclamos specialists only 6.5% (roster share 5.9%);
- Fraudes 8.9% [P4.16].

#### SQL used
```sql
-- [P4.1]
SELECT case_type, reception_channel, count(*) n, round(100.0*count(*)/sum(count(*)) over(),2) pct FROM complaints GROUP BY ALL ORDER BY 1, n DESC;
-- [P4.2]  (case-type columns returned 0 because enums are English; see P4.22)
SELECT category, coalesce(subcategory,'(null)') subcategory, count(*) total FROM complaints GROUP BY ALL ORDER BY 1, 2;
-- [P4.3]
SELECT x.reception_channel, count(*) FILTER (WHERE c.country='México') mx, count(*) FILTER (WHERE c.country='Colombia') co, count(*) FILTER (WHERE c.country='Argentina') ar, count(*) total, round(100.0*count(*)/sum(count(*)) over(),2) pct FROM complaints x JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY total DESC;
-- [P4.5]
SELECT category, coalesce(currency,'(null)') currency, count(*) n, count(claimed_amount) with_amount, round(quantile_cont(claimed_amount,0.1)) p10, round(median(claimed_amount)) p50, round(quantile_cont(claimed_amount,0.9)) p90, round(max(claimed_amount)) mx, round(avg(claimed_amount)) mean FROM complaints GROUP BY ALL ORDER BY 1, 2;
-- [P4.6]
SELECT (claimed_amount IS NULL) amount_null, (currency IS NULL) currency_null, (compensation_granted IS NULL) comp_null, count(*) n FROM complaints GROUP BY ALL ORDER BY 1,2,3;
-- [P4.7]
SELECT category, count(*) n, count(compensation_granted) with_comp, count(*) FILTER (WHERE compensation_granted > 0) comp_pos, round(median(compensation_granted)) med_comp, round(quantile_cont(compensation_granted,0.9)) p90_comp, round(median(compensation_granted/nullif(claimed_amount,0)),3) med_ratio, round(min(compensation_granted/nullif(claimed_amount,0)),3) min_ratio, round(max(compensation_granted/nullif(claimed_amount,0)),3) max_ratio, round(corr(compensation_granted, claimed_amount),3) corr_comp_claim FROM complaints GROUP BY ROLLUP(1) ORDER BY 1;
-- [P4.8]
SELECT status, (resolution IS NOT NULL) has_resolution, count(*) n, count(compensation_granted) with_comp, count(*) FILTER (WHERE compensation_granted>0) comp_pos, count(resolution_date) with_res_date, count(resolution_days) with_res_days, round(avg(resolution_satisfaction),2) res_sat, count(resolution_satisfaction) with_res_sat FROM complaints GROUP BY ALL ORDER BY 1,2;
-- [P4.9]
SELECT coalesce(resolution,'(null)') resolution, count(*) n, count(compensation_granted) with_comp, round(median(compensation_granted/nullif(claimed_amount,0)),3) med_ratio, round(avg(resolution_satisfaction),2) res_sat FROM complaints GROUP BY 1 ORDER BY n DESC;
-- [P4.10]
SELECT CASE WHEN claimed_amount IS NULL THEN 'no claim' WHEN compensation_granted IS NULL THEN 'claim, no comp' WHEN compensation_granted = 0 THEN 'comp=0' WHEN compensation_granted < claimed_amount*0.5 THEN '<50%' WHEN compensation_granted < claimed_amount THEN '50-99%' WHEN compensation_granted = claimed_amount THEN '=100%' ELSE '>100%' END bucket, count(*) n FROM complaints GROUP BY 1 ORDER BY n DESC;
-- [P4.11]
SELECT 'all' k, count(resolution_days) n, min(resolution_days) mn, quantile_cont(resolution_days,0.1) p10, median(resolution_days) p50, quantile_cont(resolution_days,0.9) p90, max(resolution_days) mx, round(avg(resolution_days),1) mean FROM complaints
UNION ALL SELECT 'priority=' || priority, count(resolution_days), min(resolution_days), quantile_cont(resolution_days,0.1), median(resolution_days), quantile_cont(resolution_days,0.9), max(resolution_days), round(avg(resolution_days),1) FROM complaints GROUP BY priority
UNION ALL SELECT 'sla_breached=' || sla_breached, count(resolution_days), min(resolution_days), quantile_cont(resolution_days,0.1), median(resolution_days), quantile_cont(resolution_days,0.9), max(resolution_days), round(avg(resolution_days),1) FROM complaints GROUP BY sla_breached
UNION ALL SELECT 'case_type=' || case_type, count(resolution_days), min(resolution_days), quantile_cont(resolution_days,0.1), median(resolution_days), quantile_cont(resolution_days,0.9), max(resolution_days), round(avg(resolution_days),1) FROM complaints GROUP BY case_type
UNION ALL SELECT 'channel=' || reception_channel, count(resolution_days), min(resolution_days), quantile_cont(resolution_days,0.1), median(resolution_days), quantile_cont(resolution_days,0.9), max(resolution_days), round(avg(resolution_days),1) FROM complaints GROUP BY reception_channel ORDER BY 1;
-- [P4.12]
SELECT CASE WHEN resolution_days IS NULL THEN 'null' WHEN resolution_days <= 5 THEN '0-5' WHEN resolution_days <= 15 THEN '6-15' WHEN resolution_days <= 30 THEN '16-30' WHEN resolution_days <= 60 THEN '31-60' ELSE '>60' END b, count(*) n FROM complaints GROUP BY 1 ORDER BY 1;
-- [P4.13]
SELECT 'case_type=' || case_type k, count(*) n, round(avg(claimed_amount)) mean_claim, round(100.0*avg((claimed_amount IS NOT NULL)::int),1) claim_fill_pct, round(100.0*avg((priority IN ('High','Critical'))::int),1) hi_pct, round(100*avg(sla_breached::int),1) sla_pct FROM complaints GROUP BY 1
UNION ALL SELECT 'channel=' || reception_channel, count(*), round(avg(claimed_amount)), round(100.0*avg((claimed_amount IS NOT NULL)::int),1), round(100.0*avg((priority IN ('High','Critical'))::int),1), round(100*avg(sla_breached::int),1) FROM complaints GROUP BY 1
UNION ALL SELECT 'segment=' || c.segment, count(*), round(avg(x.claimed_amount)), round(100.0*avg((x.claimed_amount IS NOT NULL)::int),1), round(100.0*avg((x.priority IN ('High','Critical'))::int),1), round(100*avg(x.sla_breached::int),1) FROM complaints x JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY 1;
-- [P4.14]
SELECT CASE WHEN compensation_granted IS NULL THEN 'no comp' WHEN compensation_granted=0 THEN 'comp 0' ELSE 'comp>0' END comp, CASE WHEN resolution_days <= 15 THEN 'fast<=15' WHEN resolution_days IS NOT NULL THEN 'slow>15' ELSE 'no days' END speed, count(*) n, count(resolution_satisfaction) with_sat, round(avg(resolution_satisfaction),3) sat FROM complaints GROUP BY ALL ORDER BY 1,2;
-- [P4.15]
SELECT c.country, count(*) n, round(count(*)/(1097/365.25)) per_year, count(*) FILTER (WHERE x.subcategory='Cargo no reconocido') unrec, round(count(*) FILTER (WHERE x.subcategory='Cargo no reconocido')/(1097/365.25)) unrec_per_year FROM complaints x JOIN customers c USING(customer_id) GROUP BY ROLLUP(1) ORDER BY 1;
-- [P4.16]
SELECT coalesce(a.specialty,'(generalist)') specialty, count(*) n, round(100.0*count(*)/sum(count(*)) over(),1) pct FROM complaints x LEFT JOIN service_agents a ON a.agent_id = x.assigned_agent_id WHERE x.assigned_agent_id IS NOT NULL GROUP BY 1 ORDER BY n DESC;
-- [P4.17]
SELECT category, count(DISTINCT description) n_desc, min(description) example FROM complaints GROUP BY 1 ORDER BY 1;
-- [P4.18]
SELECT count(compensation_granted) n_comp, min(compensation_granted) mn, quantile_cont(compensation_granted,0.25) q1, median(compensation_granted) med, quantile_cont(compensation_granted,0.75) q3, max(compensation_granted) mx, count(*) FILTER (WHERE compensation_granted IS NOT NULL AND claimed_amount IS NULL) comp_without_claim, round(100.0*count(compensation_granted)/count(*) FILTER (WHERE status IN ('Resolved','Closed')),1) comp_pct_of_resolved_closed, round(100.0*count(*) FILTER (WHERE compensation_granted IS NOT NULL AND claimed_amount IS NOT NULL)/count(*) FILTER (WHERE status IN ('Resolved','Closed') AND claimed_amount IS NOT NULL),1) comp_pct_with_claim, round(100.0*count(*) FILTER (WHERE compensation_granted IS NOT NULL AND claimed_amount IS NULL)/count(*) FILTER (WHERE status IN ('Resolved','Closed') AND claimed_amount IS NULL),1) comp_pct_no_claim FROM complaints;
-- [P4.19]
SELECT category, case_type, count(*) n_resolved_closed, round(100.0*avg((compensation_granted IS NOT NULL)::int),1) comp_pct FROM complaints WHERE status IN ('Resolved','Closed') GROUP BY ALL ORDER BY 1,2;
-- [P4.20]
SELECT (reception_channel='Regulator') regulator, category, count(*) n, round(100.0*count(*)/sum(count(*)) over (partition by (reception_channel='Regulator')),1) pct_within, round(100*avg((status IN ('Resolved','Closed'))::int),1) resolved_closed_pct, round(100*avg((priority IN ('High','Critical'))::int),1) hi_pct FROM complaints GROUP BY 1,2 ORDER BY 1,2;
-- [P4.21]
SELECT c.country, count(*) n_3y, round(count(*)/(1097/365.25),1) per_year, count(*) FILTER (WHERE year(x.process_date)=2024) y2024, count(*) FILTER (WHERE year(x.process_date)=2025) y2025, count(*) FILTER (WHERE x.subcategory='Cargo no reconocido') unrecognized_charge FROM complaints x JOIN customers c USING(customer_id) WHERE x.reception_channel='Regulator' GROUP BY ROLLUP(1) ORDER BY 1;
-- [P4.22]
SELECT case_type, count(*) FILTER (WHERE category='Branch') branch, count(*) FILTER (WHERE category='Fees') fees, count(*) FILTER (WHERE category='Service') service, count(*) FILTER (WHERE category='Technical') technical, count(*) FILTER (WHERE category='Transactions') transactions, count(*) total FROM complaints GROUP BY ROLLUP(1) ORDER BY 1;
-- [P4.23]
SELECT count(claimed_amount) with_amount, round(100.0*count(claimed_amount)/count(*),1) pct, count(*) FILTER (WHERE claimed_amount IS NOT NULL AND currency IS NOT NULL) amount_and_currency, min(claimed_amount) mn, max(claimed_amount) mx FROM complaints;
```

### Inferences
- **Non-random structure (usable as data-contract rules):**
  - `claimed_amount` is only on Claim/Complaint;
  - `compensation_granted`, `resolution`, `resolution_date` and `resolution_days` are only on Resolved/Closed;
  - `resolution_satisfaction` is only on Closed;
  - subcategory is 1:1 with category (F7).

  These are lifecycle and field-presence rules. An intake agent can enforce them, e.g. a Request or Suggestion never asks for an amount.
- **Random (not learnable):**
  - compensation amount and whether it is granted;
  - amount vs currency and vs category;
  - resolution days vs priority and SLA;
  - satisfaction;
  - assignment (extends F39 and F41).

  A "compensation recommender" or "SLA predictor" would be fitting noise.
- The regulator channel is small (about 239/yr) but it is the one reception channel with an obvious real-world compliance meaning. A "regulator-grade" handoff template (verified facts, timeline, amounts with currency) is a design choice, not a data finding.
- The resolution template that says compensation was granted is contradicted by `compensation_granted` in 72% of its rows [P4.9]. An agent summarising case history must read the numeric field, not the text.

### Gaps
- There are no regulator deadlines, no regulator identity and no response letters. Regulator SLAs would be our own synthetic policy.
- The `complaints.currency` fill is random (F40), so claimed amounts cannot be converted to USD reliably. No per-country currency normalisation is possible.
- `data_backup_20260831/` was not inspected (team §6.4).

## 5. Retention (3%) and Comercial (8%) contacts, and product closures: can a cancellation/retention workflow be grounded?

### Takeaway
**AI-agent verdict:** a retention workflow cannot be grounded as a measured one.
- Retención is 6,852 contacts/yr, 782 agent-h/yr, 60.2% resolved, with no segment skew.
- There are 32,039 Closed products but **no closure date and no cancellation event**.
- Customers with retention contacts are no more likely to hold Closed products (19.14% vs 19.26%).

Any save-offer logic, eligibility or save rate would be entirely synthetic. Comercial (18,272/yr, 540 s median, the longest handle time) is similarly flat.

### Cited Findings
**Retención and Comercial by segment** [P5.1]

| Reason | Segment | Contacts (3y) | Per yr | Resolved | Escalated | Follow-up | Median s | Agent-h/yr |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Retención | Basic | 12,262 | 4,083 | 59.4% | 10.0% | 49.9% | 478 | 465 |
| Retención | Plus | 5,231 | 1,742 | 61.0% | 9.7% | 48.0% | 483 | 201 |
| Retención | Premium | 2,064 | 687 | 62.7% | 9.9% | 47.0% | 472 | 79 |
| Retención | Student | 1,021 | 340 | 59.7% | 9.1% | 49.0% | 467 | 38 |
| Comercial | Basic | 32,906 | 10,956 | 65.4% | 9.9% | 44.6% | 541 | 1,410 |
| Comercial | Plus | 13,773 | 4,586 | 64.6% | 9.8% | 44.8% | 540 | 591 |
| Comercial | Premium | 5,448 | 1,814 | 66.2% | 9.7% | 43.4% | 539 | 234 |
| Comercial | Student | 2,752 | 916 | 63.9% | 9.1% | 45.5% | 535 | 117 |

- Retención is 2.98–3.04% and Comercial 7.90–8.06% of contacts in every segment [P5.2].
- Retención by channel: inbound phone 14,421, outbound 3,024, email 868, chats 2,059, video 206. Resolved 55.3–65.6% across channels [P5.3].

**Products**
- Status: Active 339,965 (85.0%), **Closed 32,039 (8.0%)**, Blocked 19,935 (5.0%), Suspended 8,061 (2.0%). The Closed share is 7.4–8.1% for every product type (e.g. Tarjeta Crédito 8,053, Cuenta Ahorro 9,716) [P5.4], [P5.5].
- **No closure date.** The products table has no closing-date column.
  - Closed products' `last_updated` spans 2018-06-29 → 2027-06-09, median 2022-12-24, the same as Active (median 2022-12-17). 6.4% are future-dated (F44).
  - `last_transaction_date` is null on all Closed, Blocked and Suspended products.
  - 0 transactions exist on non-Active products (F19) [P5.6], [P5.7].

**Retention contacts do not relate to closures** [P5.8]
- 19,274 customers had a Retención contact. Of them, 19.14% hold a Closed product vs 19.26% of the 130,726 without one.
- Customer status Closed: 2.06% vs 1.97%.

**Customer status and product status are inconsistent** [P5.9]
- Closed customers hold 85.45% Active products.
- Active customers hold 7.99% Closed products.

**Retention marketing exists but is marketing.** 62 of 200 campaigns have objective "Retention" [P8.4].

#### SQL used
```sql
-- [P5.1]
SELECT i.contact_reason, c.segment, count(*) n, round(count(*)/(1097/365.25)) per_year, round(100*avg(i.was_resolved::int),1) res_pct, round(100*avg(i.was_escalated::int),1) esc_pct, round(100*avg(i.requires_followup::int),1) fu_pct, median(i.duration_seconds) med_s, round(sum(i.duration_seconds)/3600/(1097/365.25)) hrs_per_year FROM call_center_interactions i JOIN customers c USING(customer_id) WHERE i.contact_reason IN ('Retención','Comercial') GROUP BY 1,2 ORDER BY 1,2;
-- [P5.2]
SELECT c.segment, count(*) n, round(100*avg((i.contact_reason='Retención')::int),2) retencion_pct, round(100*avg((i.contact_reason='Comercial')::int),2) comercial_pct FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY 1;
-- [P5.3]
SELECT contact_reason, channel, interaction_type, count(*) n, round(100*avg(was_resolved::int),1) res_pct FROM call_center_interactions WHERE contact_reason IN ('Retención','Comercial') GROUP BY ALL ORDER BY 1, n DESC;
-- [P5.4]
SELECT product_type, count(*) n, count(*) FILTER (WHERE product_status='Active') active, count(*) FILTER (WHERE product_status='Closed') closed, count(*) FILTER (WHERE product_status='Blocked') blocked, count(*) FILTER (WHERE product_status='Suspended') suspended FROM products GROUP BY ROLLUP(1) ORDER BY 1;
-- [P5.5]
SELECT product_status, count(*) n FROM products GROUP BY 1 ORDER BY n DESC;
-- [P5.6]
SELECT product_status, count(*) n, min(last_updated) min_lu, median(last_updated) med_lu, max(last_updated) max_lu, count(last_transaction_date) with_last_tx, median(last_transaction_date) med_last_tx, round(100.0*avg((last_updated > DATE '2026-06-17')::int),1) lu_future_pct, round(100.0*avg((expiration_date < DATE '2026-06-17')::int),1) expired_pct FROM products GROUP BY 1 ORDER BY n DESC;
-- [P5.7]
SELECT p.product_status, count(DISTINCT p.product_id) products, count(t.transaction_id) tx FROM products p LEFT JOIN transactions t USING(product_id) GROUP BY 1 ORDER BY 1;
-- [P5.8]
WITH r AS (SELECT DISTINCT customer_id FROM call_center_interactions WHERE contact_reason='Retención'),
cp AS (SELECT DISTINCT customer_id FROM products WHERE product_status='Closed')
SELECT (r.customer_id IS NOT NULL) had_retention_contact, count(*) customers, round(100*avg((cp.customer_id IS NOT NULL)::int),2) has_closed_product_pct, round(100*avg((c.customer_status='Closed')::int),2) customer_closed_pct, round(100*avg((c.customer_status IN ('Inactive','Suspended'))::int),2) inactive_or_suspended_pct FROM customers c LEFT JOIN r USING(customer_id) LEFT JOIN cp USING(customer_id) GROUP BY 1;
-- [P5.9]
SELECT c.customer_status, count(DISTINCT c.customer_id) customers, count(p.product_id) products, round(count(p.product_id)*1.0/count(DISTINCT c.customer_id),2) products_per_cust, round(100.0*avg((p.product_status='Closed')::int),2) closed_product_pct, round(100.0*avg((p.product_status='Active')::int),2) active_product_pct FROM customers c LEFT JOIN products p USING(customer_id) GROUP BY 1 ORDER BY 2 DESC;
```

### Inferences
- A cancellation agent could only do **read-only status reporting**, e.g. "your card X is Closed", from verified `products.customer_id` ownership. It cannot answer "when was it closed?" (F19) or show a save rate.
- Retención contacts are among the longest (478 s) and least resolved (60.2%). That is a real, small handle-time pool (782 h/yr), but there is no outcome or target to optimise against.
- The customer-status vs product-status inconsistency [P5.9] is a data-contract rule. The agent must never infer product state from customer status.

### Gaps
- There are no closure timestamps, no cancellation reasons, no offers and no retention outcomes. Churn, save rate and offer policy cannot be estimated.
- Comercial has no sub-intent (F1), so "commercial" demand cannot be split into sales and product-info.

## 6. Digital events: errors, foreign-IP logins, repeated failed logins, FormSubmit → Error funnels (digital-failure rescue / account-takeover step-up?)

### Takeaway
**AI-agent verdict:** neither workflow is grounded in behaviour.
- **Digital-failure rescue:** errors are a flat about 2.3% per event, binomial across 500 app versions, 5 browsers and all platforms. The event after a transfer or payment FormSubmit is an Error 2.56–2.58% of the time, the same as after any other event type. And errors do not drive contacts (F14).
- **Account-takeover step-up:** there are **zero** logins from a foreign IP country or a new city, and no failed-login field.

Digital events are usable only as **lookup records inside a conversation** (e.g. "I see an error on /transfer in your session at 14:32"). An account-takeover scenario would be synthetic.

### Cited Findings
**Scale**
- 15,620,994 events, 1,837,415 sessions [P6.0]. 24% anonymous (Q11).
- 358,723 Error events (2.30%): 179,388 Transaction + 179,335 Navigation (Q11).
- 12 page URLs, 10 actions, 12 element IDs, 500 app versions, 4 channels, 5 browsers, 16 IP cities [P6.0].

**Errors by page** (error rate = errors / all events on that page) [P6.8a]
- /transactions 57,049 (6.00%), /transfer 56,811 (5.97%), /payments 56,774 (5.96%).
- /help 42,884 (4.56%), /products 42,576, /home 42,518, /accounts 42,472 (4.51–4.52%).
- Null page 17,639.
- 0 errors on /login, /logout and the product pages.
- Errors in the "Transaction" category occur only on the 3 transaction pages.

**Errors by action** [P6.1]: view_transactions 54,073; initiate_transfer 53,883; initiate_payment 53,657; view_help 40,679; view_accounts 40,308; view_home 40,283; view_products 40,193; null 35,647.

**No platform, browser or version signal**
- Error rate is 2.264–2.309% for every channel × platform [P6.8b] and 2.265–2.306% for every browser [P6.8e].
- Across 500 app versions (16,750–19,050 events each), the rate spans 1.996–2.673% with sd 0.112 pp [P6.8c], [P6.8d]. That equals the binomial sd for p ≈ 0.023 and n ≈ 17.9K (≈ 0.112 pp; my arithmetic), so there is no "bad release".

**Sessions are generator templates** [P6.9], [P6.10], [P6.11]
- Every session starts with Login and ends with Logout (1,837,415 / 1,837,415).
- Sessions hold 2–15 events, about 131K sessions at each length.
- 0 sessions have more than 1 customer, IP, IP country or channel. Median span 4 min, max 12 min.
- 319,214 sessions (17.4%) have at least one error and 36,343 (1.98%) have two or more. The error count grows linearly with session length, about 0.03 per event.

**No FormSubmit → Error funnel** [P6.12], [P6.13]
- After a FormSubmit: next event is Error 2.56% (initiate_payment), 2.58% (initiate_transfer), 2.57% (view_transactions).
- After a PageView: Error 2.57%.
- Next event is Purchase 1.72–1.78% after a FormSubmit vs 1.72% after a PageView.
- As records: 318,316 sessions have a transfer or payment FormSubmit. 36,693 have a later Error; 32,799 have an Error and no later Purchase, of which 26,195 belong to identified customers [P6.14].

**Login and account-takeover signals**
- 2,434,770 Login events. On Login events, `action` is 'login' 1,095,401, 'logout' 1,095,724 and null 243,645 (random). There is **no failure or success field** [P6.1].
- "Repeated logins" (492,790 sessions with ≥2 Login events; 91,186 with ≥3) are mid-session Login events that the generator inserted at random [P6.9], [P6.11].
- **Foreign-IP logins: 0.** For identified customers, `ip_country` equals home country on 100% of 11.88M events (Q12).
- `ip_city` equals the customer's city on all 10,687,742 non-null events (0 mismatches; 1,187,806 null). Every customer has at most 1 distinct city [P6.15], [P6.17].
- IP addresses vary per session: a median of 10 and max of 27 distinct IPs per customer over 3 years [P6.17].
- Anonymous events use ip_country Colombia 1.23M, Argentina 1.17M, unaccented "Mexico" 1.04M (null city) and "México" 0.31M [P6.6], [P6.16]. The unaccented bucket mirrors F11.

**Repeated errors per customer** [P6.17], [P6.19]
- 128,605 customer-days have a transaction-page error. 7,264 have ≥2 and 296 have ≥3.
- The maximum is 12 errors per customer over 3 years. 31 customers have ≥10.

**Closed and Suspended customers still log in.** Logins per customer are 12.3–12.4 in every customer status, including 36,643 logins by 2,979 Closed customers [P6.18].

F14 (errors → contact 0.429%, same as logins) and F43 (`digital_events.product_id` is not the customer's) stand.

#### SQL used
```sql
-- [P6.0]
SELECT count(DISTINCT page_url) page_urls, count(DISTINCT page_title) page_titles, count(DISTINCT "action") actions, count(DISTINCT element_id) element_ids, count(DISTINCT platform) platforms, count(DISTINCT app_version) app_versions, count(DISTINCT channel) channels, count(DISTINCT browser) browsers, count(DISTINCT ip_city) ip_cities, count(DISTINCT session_id) sessions, count(*) n FROM digital_events;
-- [P6.1]
SELECT event_type, coalesce("action",'(null)') act, count(*) n FROM digital_events GROUP BY ALL ORDER BY 1, n DESC;
-- [P6.6]
SELECT (d.customer_id IS NULL) anonymous, d.ip_country, count(*) n FROM digital_events d GROUP BY ALL ORDER BY 1, n DESC;
-- [P6.8a]
SELECT coalesce(page_url,'(null)') page_url, count(*) events, count(*) FILTER (WHERE event_type='Error') errors, round(100.0*avg((event_type='Error')::int),2) error_rate_pct, count(*) FILTER (WHERE event_type='Error' AND event_category='Transaction') err_txn_cat FROM digital_events GROUP BY 1 ORDER BY errors DESC;
-- [P6.8b]
SELECT channel, coalesce(platform,'(null)') platform, count(*) events, count(*) FILTER (WHERE event_type='Error') errors, round(100.0*avg((event_type='Error')::int),3) error_rate_pct FROM digital_events GROUP BY ALL ORDER BY 1,2;
-- [P6.8c]
WITH v AS (SELECT app_version, count(*) events, avg((event_type='Error')::int) r FROM digital_events WHERE app_version IS NOT NULL GROUP BY 1)
SELECT count(*) versions, min(events) min_events, max(events) max_events, round(100*min(r),3) min_rate, round(100*quantile_cont(r,0.5),3) med_rate, round(100*max(r),3) max_rate, round(100*stddev(r),3) sd_rate FROM v;
-- [P6.8d]
(SELECT 'top' k, app_version, count(*) events, round(100.0*avg((event_type='Error')::int),3) rate FROM digital_events WHERE app_version IS NOT NULL GROUP BY 2 ORDER BY rate DESC LIMIT 5) UNION ALL (SELECT 'bottom', app_version, count(*), round(100.0*avg((event_type='Error')::int),3) rate FROM digital_events WHERE app_version IS NOT NULL GROUP BY 2 ORDER BY rate ASC LIMIT 5);
-- [P6.8e]
SELECT coalesce(browser,'(null)') browser, count(*) events, round(100.0*avg((event_type='Error')::int),3) error_rate_pct FROM digital_events GROUP BY 1 ORDER BY events DESC;
-- [P6.9]
WITH s AS (SELECT session_id, count(*) k, count(DISTINCT customer_id) n_cust, count(DISTINCT ip_country) n_ipc, count(DISTINCT ip_address) n_ip, count(DISTINCT channel) n_chan, count(*) FILTER (WHERE event_type='Error') errs, count(*) FILTER (WHERE event_type='Login') logins, datediff('minute', min(event_date), max(event_date)) span_min FROM digital_events GROUP BY 1)
SELECT count(*) sessions, round(avg(k),2) avg_events, median(k) med_events, max(k) max_events, count(*) FILTER (WHERE n_cust>1) multi_customer_sessions, count(*) FILTER (WHERE n_ipc>1) multi_ipcountry, count(*) FILTER (WHERE n_ip>1) multi_ip, count(*) FILTER (WHERE n_chan>1) multi_channel, count(*) FILTER (WHERE errs>=1) with_error, count(*) FILTER (WHERE errs>=2) with_2plus_errors, count(*) FILTER (WHERE logins>=2) with_2plus_logins, count(*) FILTER (WHERE logins>=3) with_3plus_logins, median(span_min) med_span_min, max(span_min) max_span_min FROM s;
-- [P6.10]
WITH s AS (SELECT session_id, count(*) k, count(*) FILTER (WHERE event_type='Error') errs FROM digital_events GROUP BY 1)
SELECT k events_in_session, count(*) sessions, round(avg(errs),3) avg_errs, round(100.0*avg((errs>=1)::int),2) pct_with_err, round(100.0*avg((errs>=2)::int),3) pct_2plus_err FROM s GROUP BY 1 ORDER BY 1 LIMIT 15;
-- [P6.11]
WITH o AS (SELECT session_id, event_type, row_number() OVER (PARTITION BY session_id ORDER BY event_date, event_id) rn, count(*) OVER (PARTITION BY session_id) k FROM digital_events)
SELECT 'first' pos, event_type, count(*) n FROM o WHERE rn=1 GROUP BY ALL UNION ALL SELECT 'last', event_type, count(*) FROM o WHERE rn=k GROUP BY ALL ORDER BY 1, 3 DESC;
-- [P6.12]
SELECT act, nxt, n, round(100.0*n/sum(n) over (partition by act),2) pct FROM (
 SELECT coalesce(act,'(null)') act, coalesce(nxt,'(end)') nxt, count(*) n FROM (SELECT event_type, "action" act, lead(event_type) OVER (PARTITION BY session_id ORDER BY event_date, event_id) nxt FROM digital_events) WHERE event_type='FormSubmit' GROUP BY 1,2) ORDER BY 1, n DESC;
-- [P6.13]
WITH o AS (SELECT session_id, event_type, lead(event_type) OVER (PARTITION BY session_id ORDER BY event_date, event_id) nxt FROM digital_events)
SELECT event_type, round(100.0*avg((nxt='Error')::int),2) next_is_error_pct, round(100.0*avg((nxt='Purchase')::int),2) next_is_purchase_pct, count(*) n FROM o GROUP BY 1 ORDER BY 1;
-- [P6.14]
WITH s AS (SELECT session_id, any_value(customer_id) cid,
  min(event_date) FILTER (WHERE event_type='FormSubmit' AND "action" IN ('initiate_transfer','initiate_payment')) fs,
  max(event_date) FILTER (WHERE event_type='Error') last_err,
  max(event_date) FILTER (WHERE event_type='Purchase') last_purchase
  FROM digital_events GROUP BY 1)
SELECT count(*) FILTER (WHERE fs IS NOT NULL) sessions_with_tx_formsubmit, count(*) FILTER (WHERE fs IS NOT NULL AND last_err > fs) then_error, count(*) FILTER (WHERE fs IS NOT NULL AND last_err > fs AND (last_purchase IS NULL OR last_purchase < fs)) error_no_purchase, count(*) FILTER (WHERE fs IS NOT NULL AND last_err > fs AND (last_purchase IS NULL OR last_purchase < fs) AND cid IS NOT NULL) error_no_purchase_identified, count(*) FILTER (WHERE fs IS NOT NULL AND last_purchase > fs) then_purchase FROM s;
-- [P6.15]
SELECT (d.ip_city = c.city) same_city, count(*) n FROM digital_events d JOIN customers c USING(customer_id) GROUP BY 1;
-- [P6.16]
SELECT ip_country, ip_city, count(*) n FROM digital_events GROUP BY ALL ORDER BY 1, n DESC;
-- [P6.17]
WITH x AS (SELECT customer_id, count(DISTINCT ip_city) cities, count(DISTINCT ip_address) ips, count(*) FILTER (WHERE event_type='Login') logins, count(*) FILTER (WHERE event_type='Error') errs FROM digital_events WHERE customer_id IS NOT NULL GROUP BY 1)
SELECT count(*) customers, median(cities) med_cities, max(cities) max_cities, median(ips) med_ips, max(ips) max_ips, median(logins) med_logins, median(errs) med_errs, max(errs) max_errs, count(*) FILTER (WHERE errs >= 10) cust_10plus_errors FROM x;
-- [P6.18]
SELECT c.customer_status, count(DISTINCT c.customer_id) customers, count(*) events, count(*) FILTER (WHERE d.event_type='Login') logins, round(count(*) FILTER (WHERE d.event_type='Login')*1.0/count(DISTINCT c.customer_id),1) logins_per_customer FROM digital_events d JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY 2 DESC;
-- [P6.19]
WITH x AS (SELECT customer_id, process_date, count(*) e FROM digital_events WHERE customer_id IS NOT NULL AND event_type='Error' AND event_category='Transaction' GROUP BY 1,2)
SELECT count(*) customer_days_with_txn_error, count(*) FILTER (WHERE e>=2) with_2plus, count(*) FILTER (WHERE e>=3) with_3plus, count(DISTINCT customer_id) customers FROM x;
```

### Inferences
- A "digital-failure rescue" agent can be demoed as a **grounded lookup**. Within an authenticated session, it retrieves the customer's recent Error events on /transfer or /payments. There are about 26K identified sessions with a transfer or payment submit followed by an error and no purchase [P6.14]. But no volume, benefit or deflection is measurable (F14). Error events carry no error code or message, so the explanation cannot be specific.
- An account-takeover step-up policy has no positive examples in the data. There are no foreign-IP logins, no city changes, no failed logins and no device changes [P6.9], [P6.15], [P6.17]. Any risk rule would be a labelled synthetic scenario injected into fixtures, which fits DEC-2's adversarial family.
- Closed customers still log in [P6.18]. A deployed agent needs its own session and eligibility check (DEC-7), not the data's status field.

### Gaps
- There is no error code, error message or HTTP status field, so root-cause explanations are impossible.
- There is no device fingerprint or authentication-result field. The account-takeover signal space is empty.
- The time zone of `event_date` is unknown (DEC-9).

## 7. Customer status and shared emails: implications for identity checks

### Takeaway
**AI-agent verdict:** identity and eligibility must come from a trusted session plus product-level status, never from email or `customer_status`.
- 53% of customers share an email. 54% of shared addresses span more than one country, and only 1.1% share a surname, so these are not households.
- "Closed" customers still contact the bank (13,723 contacts), transact (87,860 transactions), log in and hold 85% Active products.
- Mobile phone is effectively unique (8 shared numbers), so it is the only record-level contact field fit for an OTP factor, subject to F24.

### Cited Findings
**Contacts by customer status** (extends F26a) [P7.1]
- Active 584,388 (85.15%), Inactive 68,009 (9.91%), Suspended 20,176 (2.94%), Closed 13,723 (2.00%).
- The reason mix is the same in every status: Transaccional 33.9–35.4%, Producto 21.9–22.1%, Queja 16.5–17.2%, Técnico 14.9–15.4%, Comercial 7.8–8.4%, Retención 2.9–3.2%.
- Resolved is 76.3–77.2%.

**Customers by status:** Active 127,700, Inactive 14,914, Suspended 4,407, Closed 2,979. 98.9–99.5% of each group has at least one contact [P7.2].

**Non-Active customers remain operationally active** [P7.3], [P6.18]
- Closed: 87,860 transactions, 1,219 complaints, 36,643 logins.
- Suspended: 128,647 transactions, 1,946 complaints.

**Shared emails** (F23: 24,203 addresses, 79,930 customers) [P7.4], [P7.5], [P7.8]
- Group size runs from 2 (13,453 addresses) to 31 (1 address).
- 13,147 shared addresses (54.3%) span more than one country.
- Only 275 (1.1%) share a last name; 8,222 share a first name; 8,977 (37.1%) mix customer statuses.
- The local parts are letters only (no separators) [P7.7].
- Customers on shared emails produce 365,847 contacts (53.3%).

**Other identifiers** [P7.9]
- Mobile phone: 8 shared numbers (16 customers).
- Landline: 5 shared numbers (10 customers).
- 0 duplicate first name + last name + date of birth.
- F24: Mexican customers carry +54 prefixes. `document_number` is unique.

#### SQL used
```sql
-- [P7.1]
SELECT c.customer_status, count(*) n, round(100.0*count(*)/sum(count(*)) over(),2) pct_of_contacts, round(100*avg((i.contact_reason='Transaccional')::int),1) transacc, round(100*avg((i.contact_reason='Producto')::int),1) producto, round(100*avg((i.contact_reason='Queja')::int),1) queja, round(100*avg((i.contact_reason='Técnico')::int),1) tecnico, round(100*avg((i.contact_reason='Comercial')::int),1) comercial, round(100*avg((i.contact_reason='Retención')::int),1) retencion, round(100*avg(i.was_resolved::int),1) res_pct FROM call_center_interactions i JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY n DESC;
-- [P7.2]
SELECT c.customer_status, count(*) customers, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM call_center_interactions i WHERE i.customer_id=c.customer_id)) with_contact FROM customers c GROUP BY 1 ORDER BY 2 DESC;
-- [P7.3]
SELECT c.customer_status, count(DISTINCT c.customer_id) customers, (SELECT count(*) FROM transactions t JOIN customers c2 USING(customer_id) WHERE c2.customer_status=c.customer_status) tx, (SELECT count(*) FROM complaints x JOIN customers c3 USING(customer_id) WHERE c3.customer_status=c.customer_status) complaints FROM customers c GROUP BY 1 ORDER BY 2 DESC;
-- [P7.4]
SELECT k group_size, count(*) emails, sum(k) customers FROM (SELECT email, count(*) k FROM customers WHERE email IS NOT NULL GROUP BY 1 HAVING count(*)>1) GROUP BY 1 ORDER BY 1;
-- [P7.5]
WITH g AS (SELECT email, count(*) k, count(DISTINCT country) n_countries, count(DISTINCT last_name) n_last, count(DISTINCT first_name) n_first, count(DISTINCT customer_status) n_status FROM customers WHERE email IS NOT NULL GROUP BY 1 HAVING count(*)>1)
SELECT count(*) shared_emails, count(*) FILTER (WHERE n_countries>1) cross_country, count(*) FILTER (WHERE n_last=1) same_last_name, count(*) FILTER (WHERE n_first=1) same_first_name, count(*) FILTER (WHERE n_status>1) mixed_status FROM g;
-- [P7.7]
WITH g AS (SELECT email FROM customers WHERE email IS NOT NULL GROUP BY 1 HAVING count(*)>1)
SELECT regexp_replace(split_part(email,'@',1), '[a-z]', 'a', 'g') pattern, count(*) n FROM g GROUP BY 1 ORDER BY n DESC LIMIT 8;
-- [P7.8]
WITH s AS (SELECT email FROM customers WHERE email IS NOT NULL GROUP BY 1 HAVING count(*)>1)
SELECT (c.email IN (SELECT email FROM s)) on_shared_email, count(DISTINCT c.customer_id) customers, count(i.interaction_id) contacts FROM customers c LEFT JOIN call_center_interactions i USING(customer_id) GROUP BY 1;
-- [P7.9]
SELECT 'mobile' f, count(*) shared_values, sum(k) customers FROM (SELECT mobile_phone, count(*) k FROM customers WHERE mobile_phone IS NOT NULL GROUP BY 1 HAVING count(*)>1)
UNION ALL SELECT 'landline', count(*), sum(k) FROM (SELECT landline_phone, count(*) k FROM customers WHERE landline_phone IS NOT NULL GROUP BY 1 HAVING count(*)>1)
UNION ALL SELECT 'first+last+dob', count(*), sum(k) FROM (SELECT first_name, last_name, date_of_birth, count(*) k FROM customers GROUP BY ALL HAVING count(*)>1);
```

### Inferences
- Email-based lookup ("¿cuál es tu correo?") would resolve to multiple customers for 53% of the base, often across countries. That is a concrete adversarial test case for DEC-7: the agent must refuse to disambiguate by email alone.
- `customer_status` is a snapshot with no date, and it is inconsistent with activity and product status [P5.9], [P7.3]. An agent should state status only as "current record" and never deny service based on it without a policy rule.
- In the synthetic data, a mobile-OTP step-up is plausible because mobile is near-unique. But prefixes are not country-reliable (F24), so the OTP channel must not be used to infer country.

### Gaps
- There is no authentication log, KYC field or consent-to-contact field for service messages. Real identity-verification practice cannot be observed (F25).
- Status-change dates are absent. "Was the customer Closed at the time of the contact?" cannot be answered.

## 8. Campaign sends vs consent; is there a service (non-marketing) messaging channel to size a proactive-outreach workflow?

### Takeaway
**AI-agent verdict:** there is **no service-messaging history** to size a proactive notification workflow (card expiring, fraud confirmation).
- All 200 campaigns have marketing objectives.
- Targeting fields are not applied to recipients.
- Failure reasons ignore channel (e.g. "Invalid email address" on SMS).
- Delivery (about 94%) and open latency (median about 84 h) are identical across channels and countries.

A proactive agent can borrow only channel reach (Email 147.6K, SMS 141.6K, WhatsApp 135.3K, Push 128.4K customers ever reached) and simulated rates, as labelled assumptions. The records that would trigger notifications do exist: 56,664 expired-but-active cards (F9), 221,234 declines (F8) and 4,316 fraud transactions (F18).

### Cited Findings
**By send channel** [P8.1]

| Channel | Sends | Delivered | Opened / delivered | Clicked / opened | Conversion | Avg cost / send | Total cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| Email | 620,195 | 94.0% | 30.0% | 20.1% | 0.56% | 0.0055 | 2,903 |
| SMS | 432,283 | 94.0% | 49.9% | 20.0% | 0.94% | 0.10 | 36,704 |
| WhatsApp | 349,144 | 94.0% | n/a (not tracked) | n/a | 0.00% | 0.05 | 14,825 |
| Push | 290,650 | 94.0% | 40.1% | 20.1% | 0.77% | 0.0005 | 136 |
| Voice | 54,529 | 93.8% | n/a | n/a | 0.00% | 0.1997 | 9,277 |
| All | 1,746,801 | 94.0% | 29.7% | 20.1% | 0.56% | 0.043 | 63,844 |

- Cost currency is not stated.
- By channel × country, delivery is 93.6–94.1%, open-of-delivered is within ±0.2 pp of the channel rate, and click-of-opened is 19.8–20.4% [P8.3].

**Failure reasons are channel-agnostic** [P8.2]
- About 6% of sends fail in every channel, split into:
  - Failed / "SMTP error";
  - Bounced / "Invalid email address";
  - Blocked / "User blocked sender".
- The same email-style reasons appear on SMS (8,179 "Invalid email address"), WhatsApp (6,532), Push (5,561) and Voice (1,059).

**Open latency is the same on every channel** [P8.9]: p10 about 17 h, p50 about 84 h, p90 about 151 h for Email, SMS and Push alike. There are 0 opens before the send.
- `open_country` equals the customer's country on 100% of 438,523 non-null opens [P8.10].

**Campaign catalogue (200)** [P8.4], [P8.13]
- Objectives are only Acquisition, Cross-sell, Reactivation, Retention and Up-sell.
- Campaign types: Email, SMS, WhatsApp, Push, Voice, Mix. Mix campaigns send evenly over SMS, WhatsApp, Email and Push [P8.5].
- **No service, transactional or alert type exists.**
- Status: Completed 172, Paused 25, Active 3. 1,722,242 sends (98.6%) belong to non-Active campaigns, and 8,277 fall outside the campaign window [P8.12].
- Templates are `template_CMP-…_n` (205–375 per channel). Email has 8 distinct subjects of the form "¡Oferta especial en {producto}!", including a literal "nan" [P8.6].

**Targeting is not applied** [P8.8]
- Sends targeted at "Mexico" reach 0% México customers: the enum is unaccented vs "México".
- Colombia-targeted sends reach Colombian customers 30.2% of the time, the population share.
- Segment-targeted sends match the segment at its population share (Premium 10%, Student 5%, Basic 60%).

**Consent** (extends F26) [P8.7], [P8.15]: 50.0–50.2% of sends go to customers without marketing consent in every channel, equal to the population's 50.0% no-consent share.

**Reach and contactability** [P8.11], [P8.14]
- Customers ever reached: Email 147,646 (4.2 sends each), SMS 141,557, WhatsApp 135,303, Push 128,406, Voice 45,767.
- Customers on file with an email: 147,016; with a mobile: 145,293; with a landline: 74,947 (of 150,000).

#### SQL used
```sql
-- [P8.1]
SELECT send_channel, count(*) n, round(100.0*avg(was_delivered::int),1) delivered_pct, round(100.0*sum(was_opened::int)/nullif(sum(was_delivered::int),0),1) open_of_delivered_pct, round(100.0*sum(was_clicked::int)/nullif(sum(was_opened::int),0),1) click_of_opened_pct, round(100.0*avg(had_conversion::int),2) conversion_pct, round(avg(send_cost),4) avg_cost, round(sum(send_cost)) total_cost FROM campaign_sends GROUP BY ROLLUP(1) ORDER BY n DESC;
-- [P8.2]
SELECT send_channel, send_status, was_delivered, coalesce(failure_reason,'(null)') failure_reason, count(*) n FROM campaign_sends GROUP BY ALL ORDER BY 1, n DESC;
-- [P8.3]
SELECT s.send_channel, c.country, count(*) n, round(100.0*avg(s.was_delivered::int),1) delivered_pct, round(100.0*sum(s.was_opened::int)/nullif(sum(s.was_delivered::int),0),1) open_of_delivered_pct, round(100.0*sum(s.was_clicked::int)/nullif(sum(s.was_opened::int),0),1) click_of_opened_pct FROM campaign_sends s JOIN customers c USING(customer_id) GROUP BY ALL ORDER BY 1,2;
-- [P8.4]
SELECT campaign_type, campaign_objective, count(*) campaigns, string_agg(DISTINCT promoted_product, '|') products FROM marketing_campaigns GROUP BY ALL ORDER BY 1,2;
-- [P8.5]
SELECT m.campaign_type, s.send_channel, count(*) n FROM campaign_sends s JOIN marketing_campaigns m USING(campaign_id) GROUP BY ALL ORDER BY 1, n DESC;
-- [P8.6]
SELECT send_channel, count(DISTINCT template_used) templates, count(DISTINCT subject) subjects, min(template_used) ex_template, min(subject) ex_subject, max(subject) ex_subject2 FROM campaign_sends GROUP BY 1;
-- [P8.7]
SELECT s.send_channel, count(*) n, count(*) FILTER (WHERE c.accepts_marketing) consent_true, count(*) FILTER (WHERE NOT c.accepts_marketing) consent_false, round(100.0*avg((NOT c.accepts_marketing)::int),1) pct_no_consent FROM campaign_sends s JOIN customers c USING(customer_id) GROUP BY ROLLUP(1) ORDER BY 1;
-- [P8.8]
SELECT m.target_country, m.target_segment, count(*) sends, round(100.0*avg((m.target_country = c.country OR m.target_country IS NULL OR m.target_country IN ('All','Todos','LATAM'))::int),1) country_match_pct, round(100.0*avg((m.target_segment = c.segment OR m.target_segment IS NULL OR m.target_segment IN ('All','Todos'))::int),1) segment_match_pct FROM campaign_sends s JOIN marketing_campaigns m USING(campaign_id) JOIN customers c USING(customer_id) GROUP BY ALL ORDER BY sends DESC LIMIT 20;
-- [P8.9]
SELECT send_channel, count(open_date) opened, round(quantile_cont(datediff('minute', send_date, open_date)/60.0, 0.1),1) p10_h, round(median(datediff('minute', send_date, open_date)/60.0),1) p50_h, round(quantile_cont(datediff('minute', send_date, open_date)/60.0, 0.9),1) p90_h, count(*) FILTER (WHERE open_date < send_date) open_before_send FROM campaign_sends GROUP BY 1 ORDER BY 1;
-- [P8.10]
SELECT (s.open_country = c.country) same_country, s.open_country IS NULL open_country_null, count(*) n FROM campaign_sends s JOIN customers c USING(customer_id) WHERE s.was_opened GROUP BY ALL;
-- [P8.11]
SELECT s.send_channel, count(DISTINCT s.customer_id) customers_reached, round(count(*)*1.0/count(DISTINCT s.customer_id),2) sends_per_customer, count(DISTINCT s.customer_id) FILTER (WHERE c.customer_status<>'Active') non_active_customers_reached FROM campaign_sends s JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY 2 DESC;
-- [P8.12]
SELECT count(*) sends, count(*) FILTER (WHERE s.send_date::date < m.start_date OR s.send_date::date > m.end_date) outside_window, count(*) FILTER (WHERE m.campaign_status <> 'Active') campaign_not_active FROM campaign_sends s JOIN marketing_campaigns m USING(campaign_id);
-- [P8.13]
SELECT campaign_status, count(*) n FROM marketing_campaigns GROUP BY 1;
-- [P8.14]
SELECT country, count(*) customers, count(email) with_email, count(mobile_phone) with_mobile, count(landline_phone) with_landline FROM customers GROUP BY ROLLUP(1) ORDER BY 1;
-- [P8.15]
SELECT accepts_marketing, count(*) n, round(100.0*count(*)/150000,1) pct FROM customers GROUP BY 1;
```

### Inferences
- A proactive-outreach workflow would be a **new capability with no baseline** in the data. It is sizable only as trigger counts from records: F9 expired-but-active cards, F8 declines, F18 fraud flags.
- Channel economics can be quoted as simulated parameters, e.g. push is about 200× cheaper per send than SMS, and SMS has the highest open rate. The flat 94% delivery and random latency mean these should not be presented as observed performance differences.
- Keeping marketing out of the service workflow (DEC-8) is reinforced. Consent is independent of sends, and the targeting and failure fields are noise, so no compliant-outreach logic can be learned from history.

### Gaps
- There are no service or transactional message logs, no delivery receipts with timestamps for WhatsApp or Voice opens, and no customer channel preference. Proactive-notification uptake and response cannot be estimated.
- The cost currency and unit are undocumented outside the PDFs.

## 9. Surveys: survey_type × send_channel × response_time_hours; comment templates; any usable relevance/quality label?

### Takeaway
**AI-agent verdict:** there is no usable relevance or quality label, as expected.
- Comments are 13 templates. Their sentiment is a deterministic function of survey_type × main_score, and the score is a function of `was_resolved` (F5).
- Sub-question answers, response time, send channel and survey coverage are uniform noise.

Surveys can only anchor a labelled projection (F5), never an evaluation label for an AI agent.

### Cited Findings
**Volume:** 212,759 surveys. CSAT 127,856 (60.1%), NPS 63,668 (29.9%), CES 21,235 (10.0%) [P9.12].

**Send channel × response time** [P9.1]
- The send-channel mix is the same for every type: Email about 40%, SMS about 30%, App about 20%, IVR about 5%, Web about 5%.
- `response_time_hours` has p10 7.9–8.9, p50 18.4–18.9 and p90 28.5–29.1 (max about 36) in all 15 type × channel cells.
- The survey channel is independent of the contact channel. For example, phone contacts get 36,237 App surveys and 9,087 Web surveys [P9.10].

**Coverage is flat**
- 31.0% of contacts are surveyed: 29.2–34.5% in every reason × channel cell, and 31.0% for both resolved and unresolved [P9.7], [P9.8].
- At most 1 survey per interaction [P9.8].

**Comments** [P9.2], [P9.3]
- 13 distinct `open_comments`: 5 Negative ("Tardaron mucho en atenderme.", …), 3 Neutral ("Aceptable.", …) and 5 Positive ("Buena experiencia, gracias.", …).
- By type: CSAT has 10 distinct comments, CES 8 and NPS 8 (Negative/Neutral).

**Sentiment is a generator rule** [P9.11]
- CSAT: score 1–3 → Negative; score 4 → Positive.
- NPS: score 2–3 → Negative; score 4–7 → Neutral.
- CES: score 1–3 → Negative; score 4 → Neutral.
- About 48–52% of rows at each score have a null sentiment. A comment is present on about 95% of rows with a sentiment and 4.5% (5,018/111,502) of rows without [P9.2].
- The apparent link to `was_resolved` [P9.4] is inherited from F5.

**Sub-questions**
- There are 4 question texts, randomly null in 48 combinations [P9.5].
- Responses run 1–5 with a mean of 2.97–3.02, regardless of `was_resolved` [P9.6].

**`campaign_response_rate`** averages about 30 with thousands of distinct values, unrelated to score. Response time is about 18.5 h at every score [P9.9].

#### SQL used
```sql
-- [P9.1]
SELECT survey_type, send_channel, count(*) n, count(response_time_hours) with_rt, round(quantile_cont(response_time_hours,0.1),1) p10_h, round(median(response_time_hours),1) p50_h, round(quantile_cont(response_time_hours,0.9),1) p90_h, round(max(response_time_hours),1) max_h FROM satisfaction_surveys GROUP BY ALL ORDER BY 1, n DESC;
-- [P9.2]
SELECT survey_type, coalesce(comment_sentiment,'(null)') comment_sentiment, count(*) n, count(open_comments) with_comment, count(DISTINCT open_comments) distinct_comments FROM satisfaction_surveys GROUP BY ALL ORDER BY 1,2;
-- [P9.3]
SELECT open_comments, comment_sentiment, count(*) n FROM satisfaction_surveys WHERE open_comments IS NOT NULL GROUP BY ALL ORDER BY n DESC;
-- [P9.4]
SELECT i.was_resolved, coalesce(s.comment_sentiment,'(null)') comment_sentiment, count(*) n, round(avg(s.main_score),2) score FROM satisfaction_surveys s JOIN call_center_interactions i USING(interaction_id) GROUP BY ALL ORDER BY 1,2;
-- [P9.5]
SELECT survey_type, question_1_text, question_2_text, question_3_text, count(*) n, min(question_1_response) q1min, max(question_1_response) q1max FROM satisfaction_surveys GROUP BY ALL ORDER BY 1;
-- [P9.6]
SELECT s.survey_type, i.was_resolved, round(avg(s.question_1_response),2) q1, round(avg(s.question_2_response),2) q2, round(avg(s.question_3_response),2) q3, list(DISTINCT s.question_1_response ORDER BY s.question_1_response) q1_vals FROM satisfaction_surveys s JOIN call_center_interactions i USING(interaction_id) GROUP BY ALL ORDER BY 1,2;
-- [P9.7]
SELECT i.contact_reason, i.channel, count(*) contacts, count(s.survey_id) surveys, round(100.0*count(s.survey_id)/count(*),1) coverage_pct FROM call_center_interactions i LEFT JOIN satisfaction_surveys s USING(interaction_id) GROUP BY ROLLUP(1,2) ORDER BY 1,2;
-- [P9.8]
SELECT i.was_resolved, count(*) contacts, count(s.survey_id) surveys, round(100.0*count(s.survey_id)/count(*),1) coverage_pct, (SELECT max(k) FROM (SELECT interaction_id, count(*) k FROM satisfaction_surveys GROUP BY 1)) max_surveys_per_interaction FROM call_center_interactions i LEFT JOIN satisfaction_surveys s USING(interaction_id) GROUP BY 1;
-- [P9.9]
SELECT survey_type, main_score, count(*) n, round(avg(response_time_hours),1) avg_rt_h, round(avg(campaign_response_rate),3) avg_crr, count(DISTINCT campaign_response_rate) distinct_crr FROM satisfaction_surveys GROUP BY ALL ORDER BY 1,2;
-- [P9.10]
SELECT i.channel, s.send_channel, count(*) n FROM satisfaction_surveys s JOIN call_center_interactions i USING(interaction_id) GROUP BY ALL ORDER BY 1, n DESC;
-- [P9.11]
SELECT survey_type, main_score, coalesce(comment_sentiment,'(null)') cs, count(*) n FROM satisfaction_surveys GROUP BY ALL ORDER BY 1,2,3;
-- [P9.12]
SELECT survey_type, count(*) n, round(100.0*count(*)/sum(count(*)) over(),1) pct FROM satisfaction_surveys GROUP BY 1 ORDER BY n DESC;
```

### Inferences
- Every survey field is either a function of `was_resolved` (score, and through it sentiment and comment) or random (sub-questions, response time, channel, coverage, `campaign_response_rate`). An LLM-judge or quality model has nothing to learn from here. The team's own labelled set (DEC-2) remains the only valid evaluation label.
- The 13 comment templates can serve as seed phrasing for team-written test utterances, if labelled as such. They are not demand evidence.

### Gaps
- There are no free-text customer comments and no survey tied to a specific agent behaviour or answer. Relevance and helpfulness labels do not exist in the data.
