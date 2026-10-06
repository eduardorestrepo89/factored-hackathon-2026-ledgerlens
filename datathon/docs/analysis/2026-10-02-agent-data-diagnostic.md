# LATAM Bank data: diagnostic for the agent, and candidate customers

Factored AI & Data Hackathon 2026 · analysis date 2026-10-02 · dataset v1.0.0 · `as_of` 2026-06-17

Status: **diagnostic; its decisions are resolved by the curate stage spec (2026-10-03).** The spec is `docs/superpowers/specs/2026-10-03-curate-stage-design.md` (decisions E1–E11); the curated customers are documented in [`2026-10-03-curated-customers.md`](2026-10-03-curated-customers.md).

## 0. Summary

1. **The database is loaded correctly; the data inside it doesn't hold together per customer.** The 2026-10-02 pipeline loads all 23,495,188 rows and repairs the broken links (R1–R6). But the agent talks to one customer at a time, and what one customer's rows say contradicts itself:
   - 6,721 Active products belong to Closed customers, and Closed customers made 853 card transactions in the last 30 days (D07);
   - 56,664 cards are Active but expired, and 425,290 approvals happened after a card's expiry (D09);
   - Pending and Reversed charges never settle: median age **547 and 552 days** (D19);
   - 50,269 complaints are still Open, In Process or Escalated at a median age of **~545 days**, and a Resolved complaint never has a `closing_date` (D26). This is the "940 days open" case seen live;
   - 85% of products carry a `last_transaction_date` that isn't their last transaction (D11).
2. **Each customer is thin.** About 1 card transaction a month. Only **9,265** customers have any card transaction in the last 7 days, and no customer has more than 6 credit-card transactions in the last 30 days (D16). For most customers the session-start view is empty.
3. **Some defects can be fixed without inventing anything** (derive from other columns), **some need a team decision** (any fix invents a value), and **some can only be avoided by choosing customers.** Section 4 classifies all 39 (D38 and D39 were added on 2026-10-03).
4. **The candidate pool is small but enough.** 9,509 customers pass five hard gates (Active, adult, contactable, a usable credit card, card activity in the last 30 days). A draft richness score puts **439 in tier A** and **1,387 in tier B**. A pool-only database holds about **1.4M rows**, 6% of the full load (section 6).
5. **Some scenarios are rare in the pool:** a fraud-flagged charge in the last 90 days (16 customers), an unrecognized-charge case in the last 90 days (68), app activity in the last 24 h (63). Selection needs per-scenario quotas, not only a top-N score.

## 1. Context

### 1.1 Project state on 2026-10-02

| Area | State | Source |
|---|---|---|
| Use case | One journey, "¿Qué es este cargo?": explain → secure (card block with read-back) → dispute intake with a hand-off | `datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md` (DEC-5); `docs/LEDGERLENS_PRODUCT_DESIGN.md` v3 on `feat/database-pipeline` |
| Database | Aurora DSQL, deployed (stack `ledgerlens-bank-assistant-data`, us-east-1). Run `fc74b48e` loaded all 13 tables, 23,495,188 rows, in `public`, with repairs R1–R6 | `docs/superpowers/specs/2026-10-02-data-pipeline-design.md` |
| Access | Tool Lambdas read as `ll_read` through the private endpoint, inside the default VPC (commit `360951c`) | same spec, section 7 |
| Tools deployed alone | `list_credit_cards`, `list_card_transactions`, `get_session_context`, with `AS_OF=2026-06-17T23:59:59` | `infra-cdk/lib/data-construct.ts` |
| Agent stack | Not deployed | memory, README |
| Deadline | Submission 2026-10-05 | brief |

### 1.2 What the branches hold (research survey)

| Branch | Beyond `feat/testing-db` | Use here |
|---|---|---|
| `feat/testing-db` (current) | — | Tools, pipeline code, research notes, this analysis |
| `feat/database-pipeline` (local and origin) | `6d8b756` "Previous docs": product design v3, ERD, architecture diagram, Cedar fix | Design context (section 1.1) |
| `feat/data-pipeline`, `feat/database` | Same pipeline work with the original SHAs, plus the superseded 2026-09-29 data-loading design | None; superseded |
| `main`, `stage`, `feat/design`, `chore/remove-terraform`, `origin/feat/lambda_tools` | Nothing beyond the current branch | None |

Earlier research this document builds on, not repeats:

- `datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md`: population findings F1–F46, workflow decision.
- `datathon/research_notes/LATAM bank AI agent use cases/data_probes_transactions.md`: decline codes vs card state, fraud signal, FX, candidate density, card lifecycle.
- `datathon/research_notes/LATAM bank AI agent use cases/data_probes_operations.md`: contact centre, complaints, digital events, consent.
- `docs/superpowers/specs/2026-10-02-data-pipeline-design.md`, section 6: repairs R1–R6 and the link checks.

**What's new here:** the earlier work asked *what the population can support*. This document asks *what one customer's rows look like to the agent*, and which customers hold together.

### 1.3 How the agent reads the data

| Tool | Reads | Window (`as_of` 2026-06-17) |
|---|---|---|
| `get_session_context` | Profile; credit cards; credit-card transactions; open cases; digital signals | Transactions 72 h (90-day baseline); cases open at `as_of`; events 24 h |
| `list_credit_cards` | Credit cards in any status | Snapshot |
| `list_card_transactions` | Card transactions | `process_date` between the dates asked (default 30 days) |

A defect matters to the agent when it surfaces in one of these windows, or in a statement the agent makes ("your card is active", "this charge is pending", "your case has been open for 940 days").

## 2. Method and reproducibility

- **Data:** the local copy `datathon/analysis/bank.duckdb`, byte-identical to the organizer bucket (2026-09-29). These are the **raw values, before repairs R1–R6.** Where a repair changes a number, section 4 says so.
- **Engine:** DuckDB 1.5.5.
- **Reproduce:**

  ```bash
  cd datathon
  uv pip install duckdb==1.5.5
  python analysis/profile.py analysis/agent_readiness.sql > analysis/agent_readiness_output.txt   # ~5 s once bank.duckdb exists
  ```

  Every number cites its probe ID, `[AR-…]`. `profile.py` now skips the display step for DDL statements, so a probe file can build temp tables.
- **Windows** use `process_date`, as the tools do: d7 ≥ 2026-06-11, d30 ≥ 2026-05-19, d90 ≥ 2026-03-19.
- **Usable card** (used throughout): `product_status = 'Active'`, `expiration_date ≥ as_of`, and for credit cards a non-null `credit_limit` with `current_balance ≤ credit_limit`.
- All counts are over full populations, no sampling.

## 3. The problem in one paragraph

The generator draws each column of each table on its own, then ties child rows to parents by ID. So links hold (after R1–R6) but **states don't agree across tables or over time.** A customer's status, card status, expiry, transaction codes, complaint status and dates are independent draws. At population level that's noise. In a one-customer conversation it becomes a wrong statement. On top of that, the activity is spread thinly over 150,000 customers and three years, so a random customer has nothing recent to talk about.

## 4. Defect catalogue

**Fix classes**

| Class | Meaning |
|---|---|
| **Done** | Already repaired in the pipeline (R1–R6) |
| **Derive** | Recompute from other values in the dataset. Nothing is invented |
| **Normalize** | Map to a documented contract value (a code or spelling). Labelled as a normalization |
| **Filter** | Can't be made true without inventing values; avoid it by not selecting that customer |
| **Decide** | Any fix invents a value. The team chooses the rule, or chooses to filter or label |
| **Label** | Unfixable by design of the generator; documented, and tools never interpret it |

### 4.1 Customers and identity

| ID | Defect | Count | Agent impact | Class |
|---|---|---|---|---|
| D01 | Mexican customers carry Argentine identity formats: `document_type` DNI and `+54` mobiles | 74,907 (all of Mexico) [AR-C2] | Low: tools don't show documents or phones. Wrong if step-up auth sends to the phone | Normalize or Label |
| D02 | Gender `O` on a third of customers (49,808). Their compound names join both gender lists ("Sergio Carolina": 7,410). 746 names repeat a token ("María María") | [AR-C6], [AR-C9], [AR-C10] | The agent greets by `first_name`: "Hola Sergio Carolina" | Filter, or greet by first token |
| D03 | Under 18 at registration (minimum 13) | 3,106 [AR-C3] | A minor with credit products | Filter |
| D04 | `last_updated` after `as_of` | 9,316 customers, 25,113 products [AR-C3], [AR-P1] | Tools that order by `last_updated` (the `DISTINCT ON` queries) pick a "future" row; no visible effect today | Derive: clamp to `as_of` |
| D05 | Shared email addresses | 24,203 addresses on 79,930 customers; 13,147 shared across countries [AR-C5] | Never identity proof (DEC-7). Matters if demo logins use customer emails | Label; Filter for demo users |
| D06 | Missing email / mobile / address | 2,984 / 4,707 / 7,370 [AR-C4] | Hand-off and contact steps lack a channel | Filter |
| D07 | Customer status disagrees with products and activity: Closed customers hold Active products; Closed customers still buy | 6,721 Active products of Closed customers (33,623 of Inactive, 9,852 of Suspended) [AR-C7]; 632 Closed customers made 853 card transactions in 30 days [AR-T9] | "Your account is closed" next to a purchase yesterday | Filter: Active customers only |
| D08 | Customers with no product | 10,422 [AR-C8] (R1 sets their branch to `NULL`) | Nothing to talk about | Filter |

### 4.2 Products and cards

| ID | Defect | Count | Agent impact | Class |
|---|---|---|---|---|
| D09 | Cards Active but expired at `as_of`; approvals after the card's expiry | 40,484 credit + 16,180 debit [AR-P1]; 425,290 approvals after expiry [AR-T2] | "Your card ending 4821 is active" with an expiry in 2024 | **Decide** (options in 8.2) |
| D10 | Credit cards with no limit, no expiry, or a balance over the limit | 5,059 / 4,983 / 1,203 [AR-P1] | `available_credit` is `NULL` or negative | Filter (the card isn't usable) |
| D11 | `products.last_transaction_date` isn't the product's last transaction | 339,965 of 400,000; 270,483 have transactions after it [AR-P3] | Any "last used" statement is wrong | **Derive:** `max(transaction_date)` |
| D12 | Mexico has no MXN: Mexican products are USD; AR and CO hold ~10% USD. Mexican incomes are on a peso scale beside USD limits (limit = 0.49× income vs 6.7× in AR/CO) | [AR-P2], [AR-V4] | Amounts are quoted in USD to Mexican customers | Label (contract "Mexico = USD", DEC-9) |
| D13 | Card numbers fail the Luhn check (90%); 6 customers have two cards with the same last 4 | [AR-P4] | None if tools show only the last 4 and key on `product_id` (they do) | Label |
| D14 | Mortgages with balance over `credit_limit` | 5,854 [AR-P1] | Out of scope (cards only) | Label |
| D15 | Products used before opening; products opened before the customer registered | 117,640 products; 99,633 customers | Fixed | **Done** (R6a, R6b) |

### 4.3 Transactions

| ID | Defect | Count | Agent impact | Class |
|---|---|---|---|---|
| D16 | **Thin history.** Customers with any card transaction: 4,850 in 3 days, 9,265 in 7, 32,588 in 30, 61,735 in 90 [AR-T7]. Credit-card transactions per customer in 30 days: 1 for 18,223 customers, at most 6 [AR-T8] | — | The 72-hour session view is empty for ~97% of customers | Filter (choose active customers) |
| D17 | Status and response code disagree: Pending and Reversed rows carry decline codes; Approved rows with no code; Declined rows with no code | 83,951 Pending + 42,440 Reversed with a code; 203,369 Approved, 10,962 Declined with `NULL` [AR-T1] | "Pending, code 51 (insufficient funds)" | Approved → `'00'`: **Derive**. Pending/Reversed codes: **Decide** |
| D18 | Decline codes ignore the card. 143,520 declines are on accounts and loans; 34,077 of them say code 54 "expired card". 12,020 code-54 declines are on cards that weren't expired [AR-T2]. Only 2.5% of declines agree with the card state (probes Q1) | — | A wrong cause, unless the agent states only the code's meaning (design v3 already does) | Label + contradiction flag (design v3, 7.6) |
| D19 | Pending and Reversed never settle | 88,343 Pending (median age 547 days, 603 in the last 7 days); 44,750 Reversed (552 days) [AR-T3] | "Your charge from December 2024 is still pending" | **Decide** |
| D20 | Channel and type don't match: ATM purchases; POS deposits, transfers and withdrawals; purchases with no merchant; merchants with no category | 325,993 / 864,805 / 54,172 / 51,952 [AR-T5] | "Purchase at an ATM" | `merchant_category` from `merchant_name` (1:1 map): **Derive**. The rest: Label |
| D21 | Country spelled two ways: `Mexico` beside `México` | 40,515 rows; 18,412 of them belong to Mexican customers [AR-T6] | A Mexican purchase in Mexico shown as foreign (the session query folds accents; other queries don't) | **Normalize** to `México` |
| D22 | Amounts and times are uniform: purchases USD 5–500, every merchant's median USD 250–254, the same count in every hour of the day [AR-V1]–[AR-V3] | — | "USD 250 at Streaming Music, 3 a.m." | Label (only synthesis could fix it) |
| D23 | `fraud_score` leaks `is_fraud` (score > 30 ⇒ fraud) | F18 | Displayed, never learned (DEC-10) | Label |
| D24 | `amount_usd` missing on non-USD rows | 99,477 (F33) | No USD reference for those charges | **Derive:** `round(amount/350, 2)` for ARS, `/4000` for COP; the stored values follow that exact rule (probes Q3) |

### 4.4 Complaints (cases)

| ID | Defect | Count | Agent impact | Class |
|---|---|---|---|---|
| D25 | `affected_product_id` belongs to someone else | 44,570 | Fixed: 13,808 relinked, 30,762 → `NULL` | **Done** (R3) |
| D26 | **Status is random against age.** Open 20,125, In Process 26,823 and Escalated 3,321 have no `closing_date`, median age 525–552 days. Resolved (13,512) never gets a `closing_date` [AR-K1], [AR-K2] | — | "You have an open case from 2024", the 940-days case | **Decide** |
| D27 | Lifecycle dates after `as_of` | resolution 213, closing 47, first response 85 [AR-K3] | A case "resolved" in the future | **Derive:** point-in-time state at `as_of` (drop the future dates, roll the status back) |
| D28 | `currency` is random and `claimed_amount` doesn't scale with it (median ~2,500 in ARS, COP, MXN and USD alike); only 25% of cases with a currency use the home currency; MXN appears though no product is in MXN [AR-K4], [AR-K5] | — | "You claimed COP 2,467" (about USD 0.62) | **Decide** |
| D29 | `related_branch_id` is in another country for most cases (AR 754 of 3,812 at home) [AR-K5] | — | A branch in another country | **Derive** `NULL` where the country differs, or Label |
| D30 | `description` is one template per category ("Queja relacionada con fees") [AR-K6]; `origin_interaction_id` is always `NULL` (R5 not repaired) | — | Nothing to quote | Label |

### 4.5 Contacts, agents and digital

| ID | Defect | Count | Agent impact | Class |
|---|---|---|---|---|
| D31 | Agents handle calls before their `hire_date` | 64,179 of 686,296 [AR-I1] | Only if the hand-off cites history | **Derive** (as R6): `hire_date` = first handled interaction, if earlier |
| D32 | `mentioned_products`: 548,680 mentions, 3,562 exist, 0 owned by the caller [AR-I2] | — | Ownership trap (F21) | **Derive** `NULL` (unprovable link, the R3/R4 policy) |
| D33 | Agent country is unrelated to the customer's (38% match) [AR-I1] | — | Routing realism only | Label |
| D34 | Transcripts are two scripts with unfilled `{monto}` placeholders (F15) | 171,321 | Never quote them | Label |
| D35 | `digital_events.product_id` owned by someone else | 1,094,242 | Fixed: 337,760 relinked, 1,102,562 → `NULL` | **Done** (R4) |
| D36 | Recent app activity is rare: 897 customers in the last 24 h, 9,932 in 7 days [AR-E1] | — | The digital-signals section is empty for almost everyone | Filter / quota |
| D37 | Registration and agent branch IDs point at no branch | 149,995 customers; 831 agents | Fixed | **Done** (R1, R2) |
| D38 | Segment is unrelated to age: Students have a median age of 52 | 5,781 of 7,490 Students are over 35 (prototype, 2026-10-03) | Nothing the tools read | Label |
| D39 | Digital events pair the wrong page with the event type ("Login" on "Cerrar Sesión") | Seen in the persona checks (prototype, 2026-10-03) | None: the session signal query reads page titles and actions | Label |

### 4.6 Assumptions in the tool code that the data contradicts

| Where | Assumption | Fact |
|---|---|---|
| All 7 tool queries, `TODO(ledgerlens): R8` | "About 2 in 100 rows are duplicated"; six of them use `DISTINCT ON` to remove them | 0 primary-key or content duplicates (F27). `DISTINCT ON` is harmless but costs a sort |
| `session_open_cases.sql` | Status decides when `closing_date` is null | Correct for Resolved and Closed, but Open/In Process/Escalated are ~545 days old (D26), so cases still surface |
| `session_recent_transactions.sql` | Folds accents to compare countries | Right fix for D21 at query time; `list_card_transactions` returns the raw spelling |

## 5. What a candidate customer needs

The agent's journey needs, for one customer at `as_of`:

| Need | Why | Rule |
|---|---|---|
| Active customer, adult, with email and mobile | D03, D06, D07 | Hard gate |
| At least one usable credit card | Explain, block and dispute act on a card; D09, D10 | Hard gate |
| Card activity in the last 30 days | Something to explain; D16 | Hard gate (≥ 1), scored above that |
| A decline, Pending or Reversed charge recently | Exit 1 ("explained") | Score + quota |
| A foreign charge | Ambiguity and Portuguese-persona cases | Score + quota |
| A fraud-flagged charge (score > 30) | Exit 2 ("secured") | Score + quota |
| A recent unrecognized-charge case | Exit 3 context | Score + quota |
| Two or more usable cards | "Which card?" disambiguation | Score + quota |
| A Blocked or Suspended card | `CARD_NOT_ACTIVE` attention item | Quota |
| App activity in the last 24 h, a call in 90 days | Session signals, history | Score |

## 6. Candidate customers ("potential records")

### 6.1 Funnel [AR-S1]

| Gate | Customers |
|---|---:|
| All | 150,000 |
| Active | 127,700 |
| Adult at registration | 125,065 |
| Email and mobile present | 118,786 |
| A usable credit card | 26,591 |
| **≥ 1 card transaction on a usable card in 30 days (the pool)** | **9,509** |
| ≥ 2 such transactions | 2,170 |
| ≥ 3 such transactions | 409 |

The usable-card gate removes 78% of customers: most hold no card, or only expired, limitless or over-limit ones.

### 6.2 Draft score

```text
score = 3 × min(card tx in 30 d on usable cards, 5)
      + 2 × [decline in 30 d] + 2 × [Pending/Reversed in 30 d] + 1 × [foreign in 30 d]
      + 3 × [fraud flag in 90 d] + 2 × [unrecognized-charge case in 90 d] + 1 × [any case in 90 d]
      + 1 × [app activity in 24 h] + 1 × [call in 90 d] + 1 × [≥ 2 usable cards]
```

It's a draft, to rank; the weights aren't tuned.

| Tier | Score | Customers | Cumulative |
|---|---|---:|---:|
| A | ≥ 10 | 439 | 439 |
| B | 7–9 | 1,387 | 1,826 |
| C | 3–6 | 7,683 | 9,509 |

[AR-S4]

### 6.3 Scenario coverage in the pool [AR-S2]

| Scenario | Customers |
|---|---:|
| Decline in 7 days / 30 days | 166 / 690 |
| Pending or Reversed in 30 days | 417 |
| Foreign charge in 30 days | 600 |
| **Fraud flag (score > 30) in 90 days** | **16** |
| **Unrecognized-charge case in 90 days** | **68** |
| Any case in 90 days | 347 |
| Two or more usable cards | 2,992 |
| A Blocked or Suspended card | 603 |
| **App activity in 24 h** | **63** |
| Call in 90 days | 2,925 |
| A stale open case (created > 30 days before `as_of`, still open) | 2,662 |

**Reading:** the top of the score is dominated by transaction volume. The rare scenarios (fraud flag, unrecognized-charge case, app activity) barely reach tier A, so a top-N cut would miss them. Selection should fill scenario quotas first, then rank.

### 6.4 Country and segment [AR-S3]

| Country | Pool | Tier A | Tier B |
|---|---:|---:|---:|
| México | 4,799 | 228 | 688 |
| Colombia | 2,837 | 119 | 429 |
| Argentina | 1,873 | 92 | 270 |

Every country × segment cell (Basic, Plus, Premium, Student) has at least 6 tier-A customers, so a stratified sample by country and segment is possible.

### 6.5 Top of the list [AR-S7]

The 40 highest-scoring customers are in `analysis/agent_readiness_output.txt` under AR-S7. The top five:

| customer_id | Name | Country | Segment | Score | Usable credit/debit | Tx 30 d | Notes |
|---|---|---|---|---:|---|---:|---|
| CLI-BGY8RP21TB5E | Adriana | Colombia | Basic | 19 | 2 / 0 | 5 | Pending/Reversed and a foreign charge |
| CLI-RIUFHK8815NH | Alberto | Colombia | Plus | 19 | 2 / 0 | 5 | 2 declines; a call |
| CLI-JLLEM8RQT11E | Pilar | Colombia | Basic | 18 | 1 / 2 | 6 | A decline |
| CLI-AS8Q51DKZK2C | Martín Alberto | Argentina | Basic | 18 | 1 / 1 | 5 | A decline |
| CLI-ZS2L1VHUVAZD | Sergio Carolina | México | Plus | 18 | 2 / 0 | 5 | 2 Pending/Reversed; **D02 name** |

Even the top customer has 5 card transactions in 30 days. "Rich" here means rich *for this dataset*.

### 6.6 What the pool would carry [AR-S5], [AR-S6]

| Table | Rows for the pool | Full load |
|---|---:|---:|
| customers | 9,509 | 150,000 |
| products | 34,912 | 400,000 |
| transactions | 412,913 | 4,425,008 |
| complaints | 4,323 | 67,095 |
| call_center_interactions | 43,923 | 686,296 |
| call_transcripts | 11,039 | 171,321 |
| satisfaction_surveys | 13,755 | 212,759 |
| digital_events | 750,337 | 15,620,994 |
| campaign_sends | 111,089 | 1,746,801 |
| branches, service_agents, marketing_campaigns, daily_exchange_rates | 14,914 (all) | 14,914 |
| **Total** | **≈ 1,406,714** | 23,495,188 |

The pool's own rows still carry defects the gates don't remove: 8,209 Pending charges older than 7 days, 11,801 Pending/Reversed rows with a decline code, 4,571 code-54 contradictions, 29,029 transactions after a card's expiry (on the customer's other, expired cards), 100,482 transactions before their product's opening date (R6a fixes these), 3,839 `Mexico` spellings. So **choosing customers is not enough; the derive rules still have to run.**

## 7. Inputs for the ETL design

These are facts the design must respect, not the design.

1. **Selection removes what can't be fixed honestly** (D03, D06, D07, D08, D10, D16, part of D02). Fixing them would mean inventing closure dates, statuses or activity.
2. **Derive rules are safe and deterministic** (D04, D11, D17-Approved, D20-category, D21, D24, D27, D29, D31, D32). Each one, like R1–R6, needs evidence, an exact count and a check.
3. **The R1–R6 repairs stay** and run first; the derive rules run on repaired data.
4. **The "never delete rows" rule (D7 of the pipeline spec)** was about history inside the full dataset. A curated subset drops whole customers with all their rows, which keeps every kept customer's history intact.
5. **Scenario quotas** (section 6.3) matter more than the score.
6. **Size is a free choice.** Anything from ~50 demo customers to the whole 9,509-customer pool loads in minutes, against ~24 min for the full load.

## 8. Open decisions

**Resolved 2026-10-03.** The team chose "coherent by rule, labelled", with two changes:
- C8 reissues expired cards only when no code-54 decline after the original expiry contradicts it;
- C12 converts case amounts as well as currency.

The identity cosmetics stay labelled, and gate G4 skips mixed-gender compound names. Every row below is resolved in `docs/superpowers/specs/2026-10-03-curate-stage-design.md`, and the defect cohort keeps 159 incoherent customers as delivered for evaluation.

### 8.1 Scope

1. **How many customers, and where they live:** replace the full load in `public`, or load the subset beside it (a second schema or a second cluster)?
2. **Do the 13 tables all go into the subset,** or only the ones the agent reads (customers, products, transactions, complaints, digital events, plus dimensions)?

### 8.2 Rules that invent a value (the team picks one per row)

| Defect | Option A: fix by rule | Option B: label only | Option C: filter |
|---|---|---|---|
| D09 expired Active cards | Treat as reissued: move `expiration_date` forward by the card's own validity term until it's after `as_of` | Keep; the agent reports the expiry it sees | Not usable; customer needs another usable card |
| D19 Pending/Reversed that never settle | Pending older than N days becomes Approved `'00'` (authorisation settled); Reversed keeps its status, code → `NULL` | Keep; the agent says "pending since…" | Drop customers with old Pending rows |
| D17 decline codes on Pending/Reversed | Code → `NULL` | Keep; flag "status_code_mismatch" (design v3) | — |
| D26 stale open cases | Close cases older than the legal deadline, closing on the deadline | Keep; tools show only recent cases (design v3: "last 30 days") | Drop customers with stale open cases |
| D28 complaint currency | Currency := home currency of the customer, amount kept | Keep; never quote the amount | — |
| D01, D02 identity cosmetics | Mexico: INE and `+52`; greet by the first token | Keep | Skip gender-O compound names |

## Appendix A. Probe index

| ID | Topic |
|---|---|
| AR-SETUP-1…4 | Usable cards, card transactions with windows, per-customer profile, pool and score |
| AR-C1…C10 | Customer status, identity formats, age, missing fields, shared emails, gender, status vs products, product counts, names |
| AR-P1…P4 | Product field gaps, currency, `last_transaction_date`, card numbers |
| AR-T1…T9 | Status × code, card-state contradictions, Pending/Reversed age, product × type, channel oddities, country spelling, recency, per-customer density, activity by customer status |
| AR-V1…V4 | Amount realism, merchant medians, hour of day, limit vs income |
| AR-K1…K6 | Complaint lifecycle, stale cases, future dates, claimed amount, currency and branch country, templates |
| AR-I1, I2 | Agent hire dates and country, mentioned products |
| AR-E1 | Recent digital activity |
| AR-S1…S7 | Funnel, scenario coverage, country × segment, score distribution, defects in the pool, pool volume, top 40 |

Earlier IDs cited: F-IDs from the 2026-09-26 findings; Q-IDs from `data_probes_transactions.md`; R-IDs from the 2026-10-02 pipeline spec.
