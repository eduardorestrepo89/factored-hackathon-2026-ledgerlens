# LATAM Bank data: findings and workflow decision (v2)

Factored AI & Data Hackathon 2026 · analysis date 2026-09-26 · dataset v1.0.0

Status: **v2, revised after an adversarial data review and a judge review (§8).** Findings are reproducible. Three decision-relevant checks are still open (§6). The workflow recommendation is pending team confirmation.

## 0. Summary

1. **The dataset is a system-of-record simulator, not a behavioral log.**
   - Child rows are tied to their parents deterministically (transcripts, surveys and products carry the parent's customer and agent; survey scores are a fixed function of `was_resolved`).
   - There is **no behavioral linkage between event streams**: declines, app errors and fraud do not drive contacts or complaints, and unresolved contacts do not drive repeat contacts. This holds on full populations [K1]–[K4] and under 13 alternative definitions the reviewer tried (§8).
   - We can use the data to ground answers and power tools; we cannot mine journeys or measure deflection.
2. **The outcome and workflow labels are generator rules or random.**
   - Survey scores follow `was_resolved` exactly [D15].
   - Complaint priority, deadline breach, repeat-complainer flag, status [C3], [C7], [C8] and historical agent routing [D14] are independent of everything else.
   - So there is **no learnable ground truth** for priority, SLA or escalation. Those policies must be our own synthetic, clearly labelled rules.
3. **The supplied text cannot train or evaluate NLP.** 171,321 transcripts are two scripts with unfilled `{monto}` placeholders, independent of the labelled reason [T3]–[T7]. There is **zero Portuguese** [T1].
4. **Demand evidence is coarse.**
   - There are 6 contact reasons.
   - Transaccional and Queja each use about 12K agent-hours over three years [D13].
   - The 5 complaint categories are uniform at about 20% each [C1], [C6], so the data cannot rank sub-intents.
   - The grounded anchor for a charge workflow is **unrecognized-charge complaints (18.3% of complaint cases)**, plus 221K declined transactions and 56.7K expired-but-active cards as the records such a workflow investigates.
5. **Three authorization traps:** `complaints.affected_product_id`, `interactions.mentioned_products` and `digital_events.product_id` almost never belong to the customer on the row [A2], [A3], [A14]. Only `transactions.product_id → products.customer_id` is a trustworthy ownership join [A1].
6. **Recommendation: one journey, "¿Qué es este cargo?", with three exits** (§5 DEC-5):
   - **explained:** automated, read-only;
   - **secured:** automated write action, a confirmed card block with read-back;
   - **dispute intake:** structured handoff to the correct human queue.
   - Fallback scope is card support, triggered on 2026-10-01 if the dispute handoff isn't working end to end.

## 1. Scope, method, reproducibility

- **Data:** all 7,671 CSV files under `data/` (5,349,322,481 bytes). The local object count and byte total match the organizer bucket's `data/` prefix. The reviewer confirmed:
  - raw CSV row counts equal the loaded tables;
  - all files have a BOM, CRLF line endings and one header per table;
  - reading every column as VARCHAR gives zero cast failures against the loaded types;
  - booleans are only `True`/`False`.
- A second bucket prefix, `data_backup_20260831/`, was **not** inspected.
- **Engine:** DuckDB 1.5.5. Dimension tables use full type inference; fact tables use Hive partitioning, `union_by_name` and a 100k-row type sample.
- **Reproduce:** `uv pip install duckdb==1.5.5`, then `python analysis/profile.py analysis/profiling.sql > analysis/profiling_output.txt` (about 4 minutes on first run, 80 queries, 0 errors). Every claim cites its query ID in [brackets].
- No sampling: all tests run on full populations and are deterministic.
- **Security:** the data dictionary PDF contains the organizer's AWS keys, so `.gitignore` excludes `*.pdf`, `data/` and the DuckDB file.

## 2. What the brief rewards (source of the decision criteria)

- One coherent workflow, judged on depth ("more workflows do not earn an automatic bonus").
- A normal path, an ambiguous or unsupported request, and a human-required case, **in Spanish and Portuguese**.
- A problem supported by data: contact reasons, demand, data quality and constraints; **a baseline**; **the intended customer and business outcomes**.
- Grounded answers; report only verified actions. Permissions and policy enforced outside the model. A structured handoff (request, verified facts, actions taken, evidence, open questions).
- Data and ML rigor:
  - contracts, quality checks, lineage and a freshness policy;
  - **one learned component vs a baseline** with valid labels, no leakage and justified splits;
  - a labelled fixture for update correctness.
- Evaluation on held-out cases:
  - including incorrect or missing data, expired sessions, unauthorized access, prompt injection, tool failures and multilingual ambiguity;
  - reporting safe automated resolution (plus the share attempted), containment, escalation quality (missed and unnecessary transfers), unsafe outcomes with denominators, and p50/p95 latency plus cost per attempted case and per successful automated resolution;
  - broken down by language and segment, with repeated-run variability.
- The kickoff's three key metrics: **safe automated resolution, unsafe outcomes, cost efficiency.**

## 3. Inventory and provenance

| Table | Documented rows | Observed rows [S1] | Note |
|---|---:|---:|---|
| customers | 150,000 | 150,000 | |
| products | 400,000 | 400,000 | |
| branches | 350 | 350 | |
| service_agents | 1,200 | 1,200 | |
| marketing_campaigns | 200 | 200 | |
| daily_exchange_rates | 3,000 | 13,164 | 12 pairs × 1,097 days |
| transactions | 5,000,000 | 4,425,008 | ≈ 29.5 per customer over 3 years (≈ 0.8/month) |
| call_center_interactions | 800,000 | 686,296 | |
| call_transcripts | 200,000 | 171,321 | |
| satisfaction_surveys | 250,000 | 212,759 | |
| digital_events | 10,000,000 | 15,620,994 | |
| complaints | 80,000 | 67,095 | |
| campaign_sends | 2,000,000 | 1,746,801 | 1,083 daily files instead of 1,097 |

- Fact tables have one file per business day (1,097 days, 2023-06-17 → 2026-06-17), with identical headers across all files.
- The data is fully synthetic.

## 4. Findings

Confidence: **High** = direct count over the full population. **Medium** = inference. **Open** = not verified. "Resolved" means `was_resolved`, i.e. resolution on the contact. It is *not* a verified first-contact-resolution (FCR) figure: repeat-contact behavior does not differ by it [K4].

### 4.1 Demand and outcomes

| # | Finding | Evidence | Conf. |
|---|---|---|---|
| F1 | Contact mix: Transaccional 34.98%, Producto 21.98%, Queja 17.05%, Técnico 14.99%, Comercial 8.00%, Retención 3.00%. `reason_category` duplicates `contact_reason`, so there are no fine-grained intents | [D1] | High |
| F2 | Phone is 85% (480,678 inbound + 102,572 outbound); chat 69K; email 27.5K; video 6.8K | [D2] | High |
| F3 | Resolved on contact: Transaccional 91.5%, Producto 89.6%, Técnico 69.9%, Comercial 65.2%, Retención 60.2%, Queja 43.6%. Queja follow-up is 63.0%; median handle time is 431s vs 205s for Transaccional | [D3] | High |
| F4 | ~57K contacts/quarter, flat, no seasonality. **By business date:** Mon–Fri flat at 113–116K, Sat and Sun ~57.5K each. (Raw timestamps give a lower Monday and a higher Saturday; that is an artifact of the batch cutoff, F29.) Hour of day is uniform | [D4]–[D6] | High |
| F5 | **Survey scores are a generator rule.** CSAT and CES take values {2,3,4} when resolved and {1,2,3} when not; NPS {5,6,7} vs {2,3,4}. "+1 CSAT when resolved" restates a constant; it is not an empirical effect. We use it only as a labelled projection | [D7], [D15] | High |
| F6 | Sentiment does not predict CSAT (2.63–2.83). Accent match does not change resolution (76.68% vs 76.59%) | [D8], [D9] | High |
| F7 | Complaint categories are uniform (19.7–20.2% each; each non-null subcategory is 17.7–18.3% of all cases), and subcategory maps 1:1 to category. **"Cargo no reconocido" is 12,297 (18.3%)**, plus 1,283 Transactions complaints with a null subcategory. Deadline breach is ~20% everywhere. **70.0% are Open or In Process, and the 2023 cohort is the same (70.7%), so status is a random label, not a backlog** | [C1], [C3], [C6] | High |
| F39 | Complaint lifecycle fields are random:<br>• share High/Critical is 19.5–20.1% in every category;<br>• deadline breach is 19.2–20.5% at every priority;<br>• median first response is 37–38 hours at every priority;<br>• `is_repeat_complainer` does not match history: 3.3% of flagged vs 3.48% of unflagged complainants had a complaint in the prior 90 days | [C7], [C8] | High |
| F41 | Historical routing is random: every agent specialty handles 16.8–17.3% Queja and 34.8–35.3% Transaccional. There is **no ground truth for "correct escalation"** | [D14] | High |
| F45 | **Agent time over 3 years** (contacts with a duration): Transaccional 12,663 h (mean 221s), Queja 12,160 h (435s), Producto 9,593 h, Técnico 8,861 h, Comercial 7,061 h, Retención 2,350 h | [D13] | High |

**Operational constraints**

| # | Finding | Evidence | Conf. |
|---|---|---|---|
| F7a | 129/1,200 agents speak Portuguese (115 active); 105 are fraud specialists (96 active) | [A10], [A11] | High |
| F42 | **Portuguese-capable dispute capacity is 7 active fraud specialists (Morning 4, Afternoon 2, Rotating 1, Night 0) and 7 active complaint agents** ("Quejas y Reclamos", 64 active in total) | [A12] | High |
| F7b | Median wait is ~120s for every reason, country and segment | [D3], [D10] | High |

### 4.2 Signals an agent can verify

| # | Finding | Evidence | Conf. |
|---|---|---|---|
| F8 | 221,234 declined transactions; 210,272 carry 05, 14, 51 or 54 (~52.5K each); 10,962 have no code. Pending and Reversed rows also carry decline codes | [X2] | High |
| F46 | 203,369 Approved transactions (5.0%) have a null `response_code` | [X2] | High |
| F9 | Past `expiration_date` but still Active at dataset end: 40,484 credit cards and 16,180 debit cards (56,664 total). Over their limit: 1,203 credit cards, of which 1,015 are Active. Blocked: 4,932 credit + 2,112 debit; ~2% Suspended | [X7], [X9] | High |
| F10 | `days_past_due > 0`: 14.9% of non-null (14.2% of all credit cards); max 180 | [X8] | High |
| F11 | Brazil, Spain, USA and an unaccented "Mexico" each hold ~40.5K transactions (0.92% each, **3.66%** in total) with an identical currency mix. The unaccented "Mexico" is a separate foreign bucket, not a spelling variant (inference) | [X5] | High / Medium |
| F12 | Loans, insurance and investments only see Payment/Adjustment/Transfer. ATM "Purchase" (326K) and POS "Deposit" (214K) exist. Channel × type looks independent (inference) | [X13], [X14] | High / Medium |
| F13 | Every transaction's product belongs to that transaction's customer (4,425,008/4,425,008) | [A1] | High |

### 4.3 What the data cannot support

| # | Finding | Evidence | Conf. |
|---|---|---|---|
| F14 | No behavioral linkage between event streams: see the table below | [K1]–[K4] | High |
| F15 | Transcripts: 171,321 rows → 546 distinct full texts, 42 distinct customer texts, 2 openings (credit-card balance, savings balance). `detected_intents` is always `consulta_general` or null. Keywords are 12 permutations of {banco, cuenta, servicio}. 100% contain unfilled `{monto}`, `{moneda}` or `{limite}` | [T2]–[T6] | High |
| F16 | Transcript text is independent of the contact reason. `main_topics` equals `contact_reason` on 100% of rows, so it is a copied label | [T7], [T8] | High |
| F17 | Complaint descriptions (5), resolutions (5) and survey comments are templates | [T9] | High |
| F18 | **Fraud labels:** non-fraud scores never exceed 30, so every `fraud_score > 30` is fraud (2,373 rows = **55.0% of fraud**). Of the rest, 1,052 fraud rows score ≤ 30 and 891 have no score. Base rate 0.098% (4,316). `fraud_score` leaks the label | [X3], [X4], [X15] | High |
| F19 | Transactions exist only on currently Active products (0 on Blocked, Suspended or Closed). Status is a snapshot: "declined because the card is blocked" never appears, and "when was it blocked?" cannot be answered | [X11] | High |

**F14 detail** (full populations; the reviewer reproduced these to the third decimal)

| Test | Result |
|---|---|
| Declined → contact within 7 days | 2.854% (n = 221,234) vs Approved 2.871% (n = 4,070,681) |
| App error → contact within 1 day | 0.429% (n = 272,663) vs Login 0.429% (n = 1,850,949) |
| Fraud → complaint within 30 days | 0.927% (n = 4,316) vs 1.222%; "Cargo no reconocido" within 30 days 0.185% vs 0.229% |
| Unresolved → repeat contact | 7 days 2.87% vs 2.87%; 30 days 11.53% vs 11.65% |

- Contacts per customer are Poisson: dispersion 1.00; λ = 4.58 over all customers, 4.62 among customers with at least one contact [D12].
- Agent-level resolution rates are binomial noise: p5–p95 of 73.8–79.5% at a median of 630 contacts per agent [D11]. The reviewer found a z-score variance of 1.02.

### 4.4 Security, identity and compliance

| # | Finding | Evidence | Conf. |
|---|---|---|---|
| F20 | `complaints.affected_product_id` belongs to the complainant **0/44,570** times | [A2] | High |
| F21 | `interactions.mentioned_products`: 548,680 references, **0** owned by the caller, 545,118 (99.4%) point to products that don't exist | [A3] | High |
| F43 | `digital_events.product_id` belongs to the event's customer **16/1,094,242** times | [A14] | High |
| F22 | `complaints.origin_interaction_id` is 100% null | [C4] | High |
| F23 | 24,203 email addresses are shared by 79,930 customers (53%); 2,984 are null | [A5] | High |
| F24 | All Mexican customers have `DNI` documents and +54 mobile prefixes. `document_number` is unique | [A6], [A7] | High |
| F25 | The scripted agent turns contain no identity-check sentence. Scripts with literal placeholders say nothing about real practice, but our baseline must include an identity step | [T6] | Medium |
| F26 | 50.1% of campaign sends target customers whose *current* `accepts_marketing` is false. Consent is a snapshot (`last_updated` runs to 2027), so a historical violation is **not provable** | [A8], [Q13] | High (count) / Low (violation) |
| F26a | 2.0% of contacts come from Closed customers and 2.9% from Suspended customers | [A9] | High |

### 4.5 Data quality vs documentation (inputs to data contracts)

| # | Documented | Observed | Evidence |
|---|---|---|---|
| F27 | ~2% duplicates | 0 primary-key duplicates. 0 content duplicates on the keys tested. The reviewer also found only chance-level near-duplicates (for example, 0 transactions within 10 minutes of an identical one) | [Q1], [Q2] |
| F28 | small % of orphans | 14 of 16 foreign keys tested are clean. **`customers.registration_branch_id`: 149,995/150,000 orphans** (a random value, not a key). **`service_agents.assigned_branch_id`: 831/833 orphans** | [Q3] |
| F29 | late arrivals | **This is a fixed per-table batch cutoff, not late data and not a customer timezone.** `process_date` = event date − 1 for events before 06:00 (transactions, digital events) or 08:00 (interactions, complaints), which is 25%, 25%, 33% and 34% of rows respectively. The cutoff is the same for AR, CO and MX customers. Surveys are filed in their interaction's partition, up to 2 days before `survey_date`. The file date always equals `process_date` | [Q4], [Q4b], [Q5] |
| F44 | — | **Future-dated fields:** customers and products `last_updated` run to 2027-06-15; 211 complaint resolutions fall after the dataset end; 40,137 complaints have `first_response_date` after their file date | [Q13] |
| F30 | schema evolution | No header differences across the 1,097 files of any table; no type drift at value level (reviewer) | §3 |
| F31 | English enums | Values are Spanish (`Tarjeta Crédito`, `Queja`, `Muy Negativo`, `Pasaporte`) | [D1], [X7], [Q9], [A6] |
| F32 | MXN currency | **Transactions and products have no MXN** (Mexico is USD), and transaction currency always equals product currency. `amount_usd` is null for USD | [X6], [X10] |
| F40 | — | Complaint `currency` is random with respect to the customer's country (ARS/COP/MXN/USD at ~5.4K each, including 5,487 MXN; 1,124 Argentine complaints in MXN) and null on 67.5% | [C9] |
| F33 | realistic FX | FX rates are flat for 3 years (ARS 343–357 per USD). `amount_usd` matches FX on average (ratio 1.000); the reviewer measured up to about ±2% deviation per row (not re-run here). **99,477 non-USD rows have null `amount_usd`** (ARS 40,041, COP 59,436) | [Q6], [Q7], [X6] |
| F34 | consistent product fields | 18.7% of transactions predate `opening_date`; 48.3% come after `last_transaction_date` | [X12] |
| F35 | 1–5 / 0–10 scales | CSAT and CES take only 1–4; NPS only 2–7 (no Promoters) | [Q10], [D15] |
| F36 | — | Escalation ~10%, wait ~120s, deadline breach ~20% and transcript coverage 25% are flat in every breakdown | [D3], [C1], [C7] |

### 4.6 Fairness baseline

- **F37:** Resolved-on-contact is 76.2–77.1% and escalation 9.2–10.2% in every country × segment cell. There is no historical disparity [D10].
- **F38:** Gender, date of birth and marital status exist, and the accent fields have no outcome effect [D9]. Any disparity will be our system's, so we report every outcome by language and segment.

## 5. Decisions

### DEC-0 Intended outcomes, metrics and baseline

**Customer outcomes**

| Outcome | Target behavior |
|---|---|
| CO-1 | A verified explanation of a charge or decline in one conversation, in Spanish or Portuguese, without the ~120s queue wait (F7b) |
| CO-2 | On suspected fraud, the card is secured inside the conversation: explicit confirmation → block → read-back of the new status |
| CO-3 | An unrecognized charge becomes a complete dispute on first contact, routed to the right queue, with next steps and a synthetic service level stated |

**Business outcomes** (all offline or projected, labelled as such)

| Outcome | Definition |
|---|---|
| BO-1 | Agent-hours removed on automated exits = in-scope contacts × mean handle time × safe automated resolution rate. The in-scope share of Transaccional (12,663 h per 3 years, F45) is an **assumption** until volume data exists |
| BO-2 | Human handle time on handed-off disputes, reduced by a structured handoff vs a raw transcript |
| BO-3 | Zero unauthorized disclosures or unconfirmed actions. Reported with denominators, plus the rule-of-three upper bound when zero are observed |

**Metrics, per the brief**

| Metric | Definition |
|---|---|
| Safe automated resolution | Exit 1 or 2 is correct and policy-compliant, over all in-scope cases; also report the share attempted |
| Containment | No transfer (reported, but not treated as success) |
| Escalation quality | Correct queue, complete handoff; missed and unnecessary transfers against reference labels |
| Unsafe outcomes | Unauthorized disclosure; action without confirmation or without read-back; wrong-charge dispute; materially wrong explanation; claiming an unverified action |
| Efficiency | p50/p95 end-to-end latency; cost per attempted case and per successful automated resolution ("not defined" if there are zero successes) |

All metrics are reported by language (Spanish/Portuguese) and segment (country × Basic/Plus/Premium/Student), with n.

**Baselines, run on the same held-out cases**
- **B0 (deterministic):**
  - a keyword/menu router;
  - a lookup table from decline code to explanation;
  - a "pick from your last N transactions" list instead of a matcher;
  - always escalate on "no reconozco" or ambiguity;
  - the same authentication.
- **B1 (optional):** the same LLM without tools or guardrails, to show the unsafe outcomes a naive approach produces.
- The historical KPIs (F3) are context only, not a baseline: a different workload and random labels (F39, F41).

### DEC-1 Treat the data as the system of record, not as behavior

- Tools read records; we make no claims about journeys, deflection or causal effects.
- **Why:** F14, plus the reviewer's 13 falsification attempts (§8), all null. F5 is a generator rule.
- **Alternative rejected:** mining journeys. The joins carry no signal.

### DEC-2 Build our own labelled evaluation set, anchored to real records

- Every case is anchored to real rows (a customer, their products, a target transaction). Messages are team-written, plus LLM paraphrases from a model different from the system model.
- Expected outcomes come deterministically from the records plus our synthetic policy.
- **Splits:** by `customer_id` **and** by generator family (template, LLM paraphrase, human-written). The **human-written held-out set is the headline result.** Held-out is frozen before tuning.
- Everything is labelled "team-generated"; Portuguese cases are validated by a fluent reviewer.

**Case mix** (target ≥ 40 per family × language cell for the first three families, i.e. ≥ 320 conversations; ≥ 3 runs per case)

| Family | Cases | Expected |
|---|---|---|
| Normal | Explain a decline for codes 05/14/51/54, including code-vs-card-state contradictions; pending, reversed and foreign charges; a confirmed block | Exit 1 or 2 |
| Ambiguous / unsupported | Several candidate transactions; vague date or amount; which card (several cards); mixed Spanish/Portuguese; out of scope (credit limit increase, loan) | Clarify, or abstain and redirect |
| Human-required | Unrecognized charge; suspected fraud; vulnerable or angry customer; fee dispute (if in scope, §DEC-5) | Exit 3 to the correct queue |
| Adversarial / failure | Prompt injection in the message and in data fields (e.g. `merchant_name`); another customer's product (F20/F21/F43 traps); expired session mid-flow; failed step-up; block tool times out after confirmation; data defects (F8/F46 null codes, Pending with decline code, expired-active card F9, null `amount_usd` F33) | Refuse, re-authenticate or fall back safely; never claim an unverified action |

- Reference labels include `should_escalate` and a target queue, set by our synthetic policy (history can't supply them, F41).
- An LLM judge, if used, has a written rubric and is validated against a human-labelled sample.

### DEC-3 Do not train NLP models on the supplied text

- **Why:** two scripts and a label independent of the text (F15, F16). A row-level split would leak identical texts.

### DEC-4 Learned component: transaction matcher, behind a feasibility gate

- **Task:** a free-text description plus the conversation date → a ranking of the customer's transactions, or "no match".
- **Model:** a pairwise ranker (LightGBM LambdaRank). Features compare slots parsed from the query (amount, relative date, merchant or category words, country, currency) with candidate attributes.
- **Baseline:** hand-set scoring over **the same parsed slots**, so the comparison isolates the learning.
- **Queries:** generated from a written list of perturbation types:
  - amount rounding (±5–20%) and currency confusion;
  - relative dates ("ayer", "la semana pasada");
  - merchant paraphrase or category only;
  - country mention, typos, Portuguese phrasing.
- **Split:** by customer and by generator family, as in DEC-2.
- **No-match queries:** made-up charges, and **another customer's transaction** (which doubles as an authorization test).
- **Candidate pool:** the customer's full history, because density is low: about 29.5 transactions per customer over 3 years [S1].
- **Threshold:** the "ask vs assume" threshold is set on dev to cap the wrong-match rate at ≤ 2%, because a wrong match means a dispute on the wrong charge (an unsafe outcome). Below the threshold, the agent shows the top 3 and asks.
- **Metrics:** top-1, MRR, Recall@3, wrong-match and clarify rates, with bootstrap 95% confidence intervals by language and difficulty stratum.
- **Feasibility gate (2026-09-28):** run B0 on 200 dev queries of natural difficulty. If B0 reaches top-1 ≥ 95%, the matcher is not a credible learned component, and we switch to a **Spanish/Portuguese intent + abstention router**:
  - trained on team-written utterances split by customer and author;
  - compared with a keyword baseline;
  - measured by macro-F1, abstention precision and results per language.
  - This router drives the escalation-quality and per-language metrics directly.

### DEC-5 Workflow: "¿Qué es este cargo?", charge investigation with card-security actions and dispute intake (recommended)

**One journey, three exits**

| Exit | What happens | Type |
|---|---|---|
| **1 Explained** | Decline, pending, reversed or foreign charge, explained from verified records (status, code, card state) | Automated, read-only |
| **2 Secured** | Suspected fraud → explicit confirmation → step-up authentication → block → read-back of the status | Automated write |
| **3 Dispute intake** | Structured handoff to Fraudes, or to Quejas y Reclamos for fees (see scope) | Human |

- **Scope:** unrecognized-charge disputes are grounded in the data (F7).
- **Fee disputes** ("Cobro indebido") have no fee transaction type or category in the data. They are either out of scope, or modelled on `Adjustment` rows as a labelled assumption.

**Criteria** (unweighted; the ratings are qualitative)

| Criterion | A. ¿Qué es este cargo? | B. Account and payment inquiries | C. Card support | D. Credit info and eligibility |
|---|---|---|---|---|
| 1 Grounded demand | Medium: unrecognized-charge complaints 18.3% (F7); charge records F8, F9. Sub-intent volume is unknown (F1, F14) | Medium: Transaccional 35% / 12.7K h (F45); sub-intents unknown, and transcripts are templates (F15) | Low–medium: no card contact reason | Low: Comercial 8% |
| 2 Automatable share with checkable correctness | Exits 1 and 2 | High, but mostly read-only | Exits 1 and 2 (no dispute path) | Only against a synthetic policy |
| 3 All three case types | Natural | Human case is forced | Partial | Natural |
| 4 Learned component with valid labels and headroom | Matcher (gated, DEC-4) or router | Same matcher or router | Same | Risk model with no valid target (F10 is a snapshot) |
| 5 Security demo | Ownership traps (all options) **plus a confirmed write with read-back** | Traps, read-only | Traps plus write | Traps plus sensitive attributes |
| 6 Cost efficiency | Exits 1–2 automate short contacts; exit 3 reduces human handle time (BO-2) | Automates short contacts | Similar to A, minus BO-2 | Unclear |
| 7 Portuguese | Synthetic persona; handoff capacity 7 + 7 agents (F42) | Synthetic | Synthetic | Synthetic |
| 8 Delivery risk (deadline 2026-10-05) | Medium | Low | Low | High |

**Why A**
- It is the only option that runs the full **Understand → Decide → Act → Verify → Escalate** loop the kickoff describes, with a real write action and a structured handoff.
- Its correctness can be checked against records.
- It covers the three case types naturally.
- It is the brief's named example ("transaction-dispute intake").
- It still delivers safe automated resolutions (exits 1 and 2), not only handoffs.

**Why not B:** similar value on exit 1 but no Act/Verify step and a forced human case; the kickoff warns "don't build a chatbot".

**Why not C as primary:** C is A without exit 3, which is the strongest showcase for the handoff. **C is the fallback: if exit 3 is not working end to end by 2026-10-01, ship C.** A deployed link is mandatory for submission.

**Why not D:** three separated parts, no valid risk target, weak demand, highest scrutiny risk.

**Known weaknesses of A (accepted)**
- Declines don't generate contacts in this data (F14), so exit-1 demand is **assumed, not measured**.
- Agreement between decline codes and card state is unverified (§6.1). The data never shows declines on blocked cards (F19), and balances are snapshots, so code 51 can't be checked against a balance at transaction time. What the agent verifies deterministically:
  - the code's meaning;
  - card expiry vs transaction date;
  - card status now;
  - ownership.
  Contradictions are reported and flagged for review; AI's role is understanding, matching and clarifying.
- There are no real dispute outcomes (F17, F39): intake policy, priority and SLA are synthetic and labelled. The system's job ends at a correct intake; a human decides the dispute. No money moves.

**Handoff design (DEC-5a)**
- **Queues:** Fraudes (unrecognized charge, suspected fraud); Quejas y Reclamos (fee disputes, if in scope).
- **Portuguese routing:** the Portuguese-capable pool is 7 + 7 agents with **no Portuguese fraud specialist on nights** (F42). Fallback: Spanish fraud queue with a Portuguese summary, plus a scheduled Portuguese callback.
- **Handoff JSON:**
  - `case_id`, pseudonymous `customer_ref`, `language`, `intent`;
  - `verified_facts[{fact, source_table, source_row_id}]`;
  - `actions_taken[{action, confirmed_at, readback_status, result}]`;
  - `evidence` (transaction IDs), `open_questions`, `policy_rule_ids`, `risk_flags` (for example `fraud_score` shown as a record fact);
  - a conversation summary, **not** the raw transcript.

### DEC-6 Authorization joins (tool layer)

- Ownership is resolved only through `products.customer_id` (and `transactions.product_id → products`).
- `complaints.affected_product_id`, `interactions.mentioned_products` and `digital_events.product_id` are never used for authorization or disclosure. They become fixed regression tests (F20, F21, F43).
- Tools never infer a table from an ID prefix: the reviewer reports that `CMP-` is used for both complaints and campaigns.

### DEC-7 Identity

- Authenticate through a trusted test session: a mock identity provider, plus step-up authentication before exit 2.
- Customer number, document number, email and phone are never treated as proof (brief; F23, F24).
- Session expiry mid-flow is a tested case (DEC-2).

### DEC-8 No marketing content in this workflow

- **Why:** simplest compliant rule. The consent flag is a snapshot (F26), so we don't build on it.

### DEC-9 Business date, freshness, contracts

- `process_date` is the authoritative business date, with documented per-table cutoffs (06:00 or 08:00; surveys follow their interaction) (F29).
- The time zone of raw timestamps is **unknown**, so relative dates ("ayer") are resolved in the customer's country time zone. This is a labelled assumption.
- **As-of guards:** tools filter by an as-of date, so future-dated fields (F44) are never shown.
- Contracts encode:
  - the Spanish enums;
  - "Mexico = USD" for transactions and products (F32);
  - random complaint currency (F40);
  - nullable `response_code` and `amount_usd` (F46, F33);
  - the ownership invariant (F13).
- A **labelled fixture** (a late file, a duplicate, a changed header) demonstrates update correctness, because the supplied data contains none of these (F27–F30).

### DEC-10 `fraud_score` is displayed, never learned from

- **Why:** leakage. Every score above 30 is fraud (F18).

### DEC-11 Portuguese, honestly

- The data has **zero Portuguese demand**: customers are MX, CO and AR only; Brazil transactions are in USD/COP/ARS (F11).
- We define a labelled **synthetic Portuguese persona** (for example, a cross-border customer). A fluent reviewer validates the Portuguese cases.
- We report the Spanish–Portuguese gap with n, plus the handoff-capacity constraint (F42).

## 6. Open items

1. **Decline codes vs card state** (code 54 vs expiry at transaction time; code 51 vs limit). Not run: awaiting team approval. Decides how much of exit 1 is automatable without a "contradiction" flag.
2. **Home country vs transaction country per customer** (who travels where). Awaiting team approval. The currency-bucket inference (F11) stands in for it meanwhile.
3. **Per-customer candidate density** (transactions per customer per 7- and 30-day window, same-merchant repeats). Awaiting team approval. It feeds the DEC-4 feasibility gate; the gate itself stays as the safeguard.
4. **`data_backup_20260831/`** in the bucket has not been inspected; it may hold the documented duplicates, late files or schema changes.
5. **Per-row `amount_usd` deviation** (about ±2%): reported by the reviewer, not re-run.
6. **Offline only:** synthetic independence means no offline improvement transfers to a production claim. Offline, simulated and projected numbers are labelled separately.

## 7. Corrections log

| Earlier claim | Correct value | Evidence |
|---|---|---|
| "77% of complaints still Open/In Process" | 70.0% (74.9% including Escalated); 77.2% have no resolution text. Also a random label, not a backlog | [C3] |
| "`is_fraud` fully determined by `fraud_score ≥ 50`" (chat), later "≥ 50 covers 39%" (v1) | Score > 30 means fraud and covers 55.0% of fraud | [X15] |
| "58,711 customers share an email" | 24,203 shared addresses covering 79,930 customers | [A5] |
| "59 fraud-specialist phone agents" / "96, Portuguese-capable when needed" (v1) | 105 fraud specialists (96 active); **7** active Portuguese-capable, 0 on nights | [A11], [A12] |
| "~210K declines" | 221,234 declined; 210,272 with a code | [X2] |
| Tue–Fri peak, Monday lower (v1 F4) | An artifact of raw timestamps; by business date Mon–Fri is flat | [D5] |
| "Business day = UTC−6" (v1 F29, DEC-9) | A per-table batch cutoff (06:00/08:00), the same for every country; time zone unknown | [Q4], [Q4b] |
| "No MXN amounts at all" (v1 F32) | True for transactions and products; complaints hold 5,487 MXN (random currency) | [C9] |
| "Resolution drives CSAT" (v1 F5) | A generator rule, not an effect | [D15] |
| "Tables are statistically independent" (v1 §0) | Child tables are tied to parents; there is no *behavioral* linkage between event streams | §0.1 |
| "Disputes and fees = 36.5% of complaints" as demand for A (v1 DEC-5) | 18.3% grounded (unrecognized charges); fees have no records behind them | [C1] |
| "70% unresolved" as headroom (v1 DEC-5) | A random status label; removed | [C3] |
| Sampled cause-and-effect percentages (chat) | Full-population results in F14 | [K1]–[K4] |

## 8. Review log

**Adversarial data review**
- **Loader:** sound. Raw CSVs match the tables.
- **Refuted:** F4, F29, F32.
- **Partial:** F10, F11, F18, F28, F33.
- **Overreach:** F5, F26, §0.1.
- **Verified:** everything else, including all of F14 (reproduced independently with ASOF joins) and F18, F20, F21, F23 and F26 recomputed from raw CSVs.
- **Falsification:** 13 alternative definitions all came back null. Examples:
  - declines → Transaccional contacts at 1/3/7 days;
  - errors on transaction pages → Técnico contacts;
  - fraud → complaints at 7/90 days;
  - Queja contact ↔ complaint within ±3 days;
  - `claimed_amount` never equals a prior transaction (0/21,751);
  - customer-level correlations |r| ≤ 0.002.
- **Missed patterns now added:** F39, F40, F41, F43, F44, F46, and the 7-agent Portuguese pool.
- **Conclusion:** the workflow recommendation stands. Narrow disputes to unrecognized charges, treat DEC-4 as the main delivery risk, and size the Portuguese handoff at 7 agents.

**Judge review: ACCEPT WITH REVISIONS**

| Criterion | Score |
|---|---|
| Evidence | 3 |
| Brief coverage | 3 |
| Decision | 3 |
| ML rigor | 2 |
| Safety | 3 |
| Honesty | 4 |
| Clarity | 4 |

- Spot checks: 8/8 numbers matched.

**What changed from v1 because of the reviews**
- DEC-0 (outcomes, metrics, baselines) added.
- DEC-2 gained the case-mix table and failure/adversarial families.
- DEC-4 got a named model, a shared-input baseline, a perturbation taxonomy, generator-family splits, a no-match class, a threshold rule and a feasibility gate with a fallback component.
- DEC-5 reframed as one journey with three exits (card actions moved into the core). The criteria table was rebalanced with a cost criterion, "weighted" dropped, a dated fallback trigger added, Queja headroom and "70% open" removed.
- DEC-5a handoff queues and JSON; the Portuguese capacity fact.
- F5, F12, F25, F26 and F29 downgraded to what the evidence supports.
- DEC-8 simplified; DEC-9 per-table cutoffs and as-of guards; DEC-11 honest Portuguese persona.

**Not acted on**
- The judge asked for the decline-code check to be run now (§6.1). Not done: it needs team approval.
- The reviewer measured per-customer candidate density (§6.3) without being asked, inside a scope that is awaiting approval. Those numbers are withheld from this document pending the team's decision.

## Appendix: reproduction

```bash
uv venv && uv pip install duckdb==1.5.5
python analysis/profile.py analysis/profiling.sql > analysis/profiling_output.txt   # 80 queries
# header-drift check (F30): prints 1 per table
for t in call_center_interactions call_transcripts campaign_sends complaints digital_events satisfaction_surveys transactions; do
  find data/$t -name '*.csv' -exec head -1 {} \; | sort -u | wc -l; done
```
