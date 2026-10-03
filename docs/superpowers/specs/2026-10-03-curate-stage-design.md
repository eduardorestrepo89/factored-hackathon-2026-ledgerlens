# LedgerLens curate stage: design

- **Date:** 2026-10-03
- **Branch:** `feat/testing-db` (design); implementation branch chosen in the plan
- **Status:** implemented on `feat/curate-stage` (plan `docs/superpowers/plans/2026-10-03-curate-stage.md`). Counts below are the pinned full-data counts in `data_load/expected.json` → `curation`, from the 2026-10-03 rehearsal.
- **Builds on:** `docs/superpowers/specs/2026-10-02-data-pipeline-design.md` (stages, repairs R1–R6, access). This spec adds a stage between transform and load and changes what load reads. Everything else in that spec stands.
- **Evidence:**
  - `datathon/docs/analysis/2026-10-02-agent-data-diagnostic.md`: defects D01–D37, candidate funnel, probes AR-*.
  - `datathon/reports/Agent evaluation signal on AWS.md`: why a coherent base matters for verifiable evaluation labels.
- **Follow-up sub-project:** the evaluation harness (`POLICY.md`, label functions, mutation ops, case generator, graders, AgentCore Evaluations runner). It gets its own spec. This stage only prepares its inputs.

## 1. Goal

Add a **curate** stage that turns the full repaired data (`clean/<run-id>/`, 23,495,188 rows) into the data the agent is served and tested on. The stage runs once per pipeline run:

1. **Fix what can be fixed honestly.** Twelve curation rules (C1–C12) make each customer's rows agree with each other. Seven derive values from other columns. Five are labelled synthetic rules.
2. **Select about 1,500 coherent customers.** They are spread evenly over the 12 country × segment cells, including 10 pinned demo personas, one per use case.
3. **Keep 159 incoherent customers as delivered.** This defect cohort covers 17 defect classes, so the agent is also tested on bad data. Each customer carries evidence row IDs for later labelling.
4. **Replace `public` in Aurora DSQL with this curated set.** The full repaired data stays in S3 `clean/` for lineage and analysis.

The tools, schema, grants, indexes and read check do not change.

## 2. Facts this design rests on

These facts come from a throwaway prototype run on 2026-10-03. The run used the local transform output, which reproduced the R1–R6 counts in `data_load/expected.json` exactly. The rehearsal pins the final counts.

| Fact | Consequence |
|---|---|
| The agent talks to one customer at a time, but each customer's statuses, expiry, codes and case states are independent random draws (diagnostic §3) | Fix within a customer's rows, then select customers |
| The data is thin: about 97% of customers have no card charge in the last 3 days (diagnostic D16) | Score customers by recent activity |
| C2's evidence: Python's float `round(amount/rate, 2)` reproduces all 1,887,552 stored `amount_usd` values. DuckDB's `round` misses 1,089 half-cents | C2 computes in plain Python. A DuckDB Python UDF needs numpy and ran ~600× slower (95 s per 200,000 rows), so it was rejected |
| C3's evidence: every named merchant has exactly one `merchant_category` (the `NULL` merchant group is excluded) | The category can be derived from the merchant |
| A blanket card reissue turned 239 of the 510 code-54 declines from the last 30 days into false contradictions; those cards really were expired on the decline date | C8 skips any card with code-54 evidence after its original expiry: 5,171 cards, whose 1,424 pool customers aren't selectable |
| After the C-rules and the gates (section 6.1), 14,999 customers remain, and every country × segment cell holds at least 154 | 125 per cell works |
| Each of the 17 defect classes has at least 235 raw customers with card activity in the last 30 days | 20 per class works |
| Selection by flags alone picked oddities, such as a cash Withdrawal at a POS for a "decline" persona | Personas need an evidence row: a credit-card Purchase with a merchant, on POS, App or Web, inside the tool's window |

## 3. Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| E1 | A **separate stage**, between transform and load | It shows as its own node in Step Functions and reruns alone in ~3 min while selection is tuned; `clean/` keeps the full repaired data | Inside transform (any retune reruns it and the full data is lost); ELT in DSQL (24-min load every time) |
| E2 | **`public` holds only the curated set**: 1,500 clean + 159 defect customers, all their rows, all four dimension tables | Tools stay unchanged; load drops from ~24 to ~2 min | Curated set in public with the full data in a second schema (load stays ~27 min); a new schema (all 7 tool SQL files change) |
| E3 | **Rules C1–C12 run on every row**; output is filtered afterwards | Rule counts are population facts and pinned like R1–R6 | Rules on the selected subset only (counts would drift with the selection) |
| E4 | **Synthetic rules are allowed and labelled** (C8–C12) | Without them, only 1,163 customers pass and 169 are rich (tier A/B); rare scenarios vanish | Derive and filter only |
| E5 | **C8 is evidence-aware** | A blanket reissue would erase 239 correct "expired card" declines in 30 days | A blanket reissue; filtering every expired card (rare scenarios drop by ~65%) |
| E6 | **C12 converts amounts as well as currency** | Case amounts don't scale with their currency (median ~2,500 in every currency), so changing only the currency would make "COP 2,467" (≈ USD 0.62) | Currency only |
| E7 | **Balanced cells: 125 × 12**, not proportional | Every language and segment stratum gets enough customers for per-stratum reporting (Argentina × Student would get ~15 proportionally) | Proportional allocation; global top-N |
| E8 | **No rare-scenario quotas** | The evaluation harness injects rare situations into clones; curation only provides a coherent base | Quotas for fraud flags, open cases and app activity |
| E9 | **A defect cohort at the silver level** (R1–R6 applied, C-rules not) | Tests the agent on incoherent data while the link contract holds; ownership traps get injected by the harness with known labels | Raw links too (link checks would fail; labels unverifiable) |
| E10 | **10 pinned personas** in `data_load/personas.json`; a persona failing a gate fails the stage | Demo logins can't silently break | Personas re-picked every run |
| E11 | **The `EVL-` ID prefix is reserved** for the harness's injected clones | Clones can live in `public` next to real customers, isolated by ID, with no tool change | A separate eval schema |

## 4. Pipeline

### 4.1 Stages

```text
Ingest → Transform → Curate (new) → Load → ReadCheck
 raw/      clean/      curated/       DSQL public
```

| Stage | Change |
|---|---|
| Transform | None. Still writes `clean/<run-id>/<table>.parquet` and `runs/<run-id>/transform.json` |
| **Curate** (`python -m data_load curate`) | New. Reads `transform.json` and downloads `clean/<run-id>/` (~1.2 GB) into an on-disk DuckDB. Snapshots the defect cohort, applies C1–C12, runs the gates and the selection, filters the 13 tables and runs the checks. Writes `curated/<run-id>/<table>.parquet` + `.sha256` and `runs/<run-id>/curate.json`. `--source <dir>` reads a local `clean/` directory with no S3, for rehearsals |
| Load | Reads `runs/<run-id>/curate.json` instead of `transform.json`; everything else is unchanged. A missing `curate.json` fails with "run curate first" |
| ReadCheck | None |

The Step Functions chain gains `stage("Curate")` between Transform and Load. CodeBuild runs it with `STAGE=curate`. To rerun curate alone:

```bash
aws codebuild start-build --project-name ledgerlens-data-load \
  --environment-variables-override name=STAGE,value=curate name=RUN_ID,value=<run-id>
```

Then rerun `load` the same way.

### 4.2 Order inside curate

1. Load the 13 clean tables into DuckDB.
2. **Evidence checks** (preconditions): every named merchant has one category; C2's Python rounding reproduces every stored `amount_usd`; no `customer_id` starts with `EVL-`.
3. **Defect cohort:** compute the 17 classes on the clean values, select the cohort (section 7) and snapshot its rows from the four tables the C-rules change: customers, products, transactions and complaints. The other customer-linked tables are untouched by the rules.
4. **C-rules C1–C12**, in order, over all rows. Each rule writes its fixes to a temp table first, so the count comes from the same rows the update changes (the `repair.py` pattern).
5. **Gates and selection** of the clean customers (section 6), excluding the cohort.
6. **Output:**
   - clean customers' rows from the fixed tables;
   - cohort customers' rows from the snapshot;
   - dimension tables whole.
7. **Checks** (section 8), then Parquet, SHA-256 and the run record.

## 5. Curation rules

Counts are from the prototype over all rows; the rehearsal pins them in `expected.json` → `curation.rules`. "as_of" is `2026-06-17 23:59:59` (`DATE '2026-06-17'` for dates).

### 5.1 Derive rules: nothing invented

| Rule | Column | Rule | Evidence | Rows | Invariant (clean customers) |
|---|---|---|---|---:|---|
| C1 | `transactions.transaction_country` | `'Mexico'` → `'México'` | Same Mexican cities under both spellings (D21) | 40,515 | 0 `'Mexico'` |
| C2 | `transactions.amount_usd` | `NULL` on ARS/COP → Python `round(float(amount) / {ARS: 350, COP: 4000}, 2)` | Reproduces all 1,887,552 stored values (D24) | 99,477 | 0 non-USD rows with `NULL` |
| C3 | `transactions.merchant_category` | `NULL` with a merchant → that merchant's only category | One category per named merchant (D20) | 51,952 | 0 merchants without a category |
| C4 | `transactions.response_code` | Approved with `NULL` → `'00'` | `'00'` is the only code on 3,867,312 Approved rows (D17) | 203,369 | 0 Approved with `NULL` |
| C5 | `products.last_transaction_date` | := `max(transaction_date)` of the product, `NULL` if none | — (D11) | 339,965 | Equal for every product |
| C6 | `customers.last_updated`, `products.last_updated` | > as_of → as_of | — (D04) | 9,316 + 25,113 | 0 after as_of |
| C7 | `complaints` lifecycle | A case with `assignment_date`, `first_response_date`, `resolution_date` or `closing_date` after as_of becomes its state at as_of. Future dates → `NULL`; resolution text, days, compensation and satisfaction → `NULL` if the resolution is in the future. Status := Closed if closed ≤ as_of; else Resolved if resolved ≤ as_of; else In Process if responded or assigned ≤ as_of; else Open | Point-in-time state (D27) | 283 | 0 lifecycle dates after as_of |

### 5.2 Synthetic rules: labelled in the run record and docs

| Rule | Column | Rule | Rows | Invariant (clean customers) |
|---|---|---|---:|---|
| C8 | `products.expiration_date` | A card (credit or debit) with `product_status = 'Active'` and `expiration_date < as_of` is **reissued**. Term t = `least(5, greatest(3, date_diff('year', opening_date, expiration_date)))`; new expiry = expiry + t × ((year(as_of) − year(expiry)) // t + 1) years, which always lands after as_of. **Exception:** a card with any Declined code-`54` transaction whose `transaction_date::DATE` is after its original `expiration_date` keeps its expiry (evidence it really was expired) | 51,493 reissued; 5,171 kept | 0 Active cards expired at as_of |
| C9 | `transactions.transaction_status`, `response_code` | Pending with `process_date ≤ as_of − 7 days` → Approved, `'00'` (the authorization settled) | 87,740 | 0 Pending older than 7 days |
| C10 | `transactions.response_code` | On Pending and Reversed → `NULL` | 43,006 | 0 Pending/Reversed with a code |
| C11 | `complaints` | A case past the legal answer deadline: days = AR-CLAIM 14, CO-PQR 21, MX-UNE 42 (calendar-day equivalents of 10/15/30 business days, design v3 §9), by the customer's country. Open, In Process or Escalated with no `closing_date` and creation + days ≤ as_of → Closed; `resolution_date = closing_date = creation + days`; `resolution_days = days`; `resolution = 'Cerrado al vencer el plazo legal de respuesta (<rule id>); regla sintética C11'`. Rejected with no `closing_date` → `closing_date = creation + days`, status stays Rejected | 48,943 closed; 685 Rejected dated | 0 open cases past their deadline |
| C12 | `complaints.currency`, `claimed_amount`, `compensation_granted` | Home currency by country: Argentina ARS, Colombia COP, México USD (contract "Mexico = USD"). Amounts are treated as USD and × book rate (350 / 4000 / 1), rounded to 2 places. `currency = NULL` when both amounts are `NULL`. Counts only rows whose values change (a Mexican case already in USD is not one) | 23,299 | Currency = home currency wherever an amount exists |

### 5.3 Kept as delivered, labelled

D01 (Mexican identity formats), D12 (Mexico in USD), D13 (Luhn), D14 (mortgages over limit), D18 (remaining code contradictions; the explain tool flags them), D20 (channel/type oddities apart from C3), D22 (uniform amounts and hours), D23 (`fraud_score` leaks the label), D30–D34 (template text, contacts and agents) and two new defects found in the prototype:

- **D38:** segment is unrelated to age. Student has a median age of 52; 5,781 of 7,490 Students are over 35.
- **D39:** digital events pair the wrong page with the event type ("Login" on "Cerrar Sesión"). The session signal query reads page titles and actions, so its signals are unaffected.

## 6. Selection of the clean customers

### 6.1 Gates (all must hold)

| # | Gate | On |
|---|---|---|
| G1 | `customer_status = 'Active'` | customers |
| G2 | 18 or older at `registration_date` (after R6b) | customers |
| G3 | `email` and `mobile_phone` not `NULL` | customers |
| G4 | Clean first name: no repeated token ("María María"), not a compound of a male-list and a female-list name ("Sergio Carolina"). The name lists come from M/F customers' first tokens used by one gender only | customers |
| G5 | ≥ 1 **usable** credit card: Active, `expiration_date ≥ as_of`, `credit_limit` not `NULL`, `current_balance ≤ credit_limit` | products (after C8) |
| G6 | Every Active card has an `expiration_date`, and every Active credit card has a `credit_limit` | products |
| G7 | No Active card expired at as_of (the C8 exception cards) | products (after C8) |
| G8 | ≥ 1 card transaction on a usable card with `process_date > as_of − 30 days` | transactions (after C-rules) |

The pinned funnel: 127,700 (G1) → 121,256 (G2) → 115,174 (G3) → 108,888 (G4) → 41,648 (G5) → 38,928 (G6) → 37,696 (G7) → **14,999** (G8). G2 uses exact age (`date_of_birth + 18 years <= registration_date`).

### 6.2 Score

```text
score = 3·min(card tx in 30 d on usable cards, 5)
      + 2·[decline 05/14/51 in 7 d] + 2·[Pending in 7 d] + 2·[Reversed in 30 d] + 3·[fraud_score > 30, Approved, in 30 d]
      + 2·[open unrecognized-charge case] + [code-54 decline in 30 d] + [foreign charge in 30 d]
      + [digital event in 24 h] + [call in 90 d] + [≥ 2 usable cards] + [Blocked/Suspended credit card] + [past-due usable credit card]
```

All windows use `process_date`, except digital events, which use `event_date`, as the session tool does. "Foreign" compares countries with accents folded.

### 6.3 Allocation

1. The 10 personas (section 6.4) are selected first. Each must pass G1–G8, or the stage fails naming the persona and the gate.
2. Each of the 12 country × segment cells gets `--customers / 12` customers; the default is 1500, so 125 per cell. The flag must be a multiple of 12. Personas count toward their own cell.
3. Within a cell, customers are ordered by score descending, ties by `md5(customer_id)`. The same data always gives the same selection.
4. A cell with fewer gated customers than its share takes all of them; the shortfall is recorded in `curate.json`. There is no top-up from other cells.
5. Defect-cohort customers are excluded.

### 6.4 Personas

`data_load/personas.json` pins these 10. Evidence is a credit-card Purchase with a merchant, on POS, App or Web, inside the tool's window.

| # | Use case → expected outcome | Customer | Evidence |
|---|---|---|---|
| P01 | Decline explained → exit 1 | `CLI-1GL7QBDG3QG0` Rocío Isabel López García, CO, Plus | `TRX-SSJAIUCVVU1L4605ZLNM` 2026-06-17 18:25 Restaurante El Buen Sabor USD 128.30, Declined 51, card `PRD-GKI6NTZU2AEX` (6811) |
| P02 | Pending charge → exit 1 | `CLI-7EC6UCDZMSKV` Martín Romero Fernández, AR, Basic | `TRX-M8SV89D2QGIE6WRUB79K` 06-17 20:07 Farmacia Salud ARS 125,356.26, Pending, card 2196 |
| P03 | Reversed charge + app context → exit 1 | `CLI-70U0WJ1NH1MN` Laura Acosta Acosta, AR, Plus | `TRX-LJGEBUAOX0G4CL4RQSIU` 06-16 03:33 Laboratorio Central ARS 129,811.06, Reversed, card 8910; app view of "Tarjeta de Crédito" on 06-17 |
| P04 | Which card? → clarify | `CLI-N4FPJIEGD917` Óscar Diego Gutiérrez Rodríguez, CO, Plus | Mercado Central on two cards: `TRX-19B2TR7A8QXK7243KZV6` USD 74.52 Pending (2218) and `TRX-9TDT782N9PARVY8IMPRE` COP 1,973,645.12 (5384) |
| P05 | Portuguese persona, foreign charge | `CLI-50OIF5EIYSWK` Alejandro Torres Ortiz, MX, Plus | `TRX-MQKFELIPWT098DXTN2WN` 06-17 13:29 Super Ahorro USD 128.67 in Brazil; `TRX-YLR3CXW0CFHFUNT2IUWZ` 06-14 Declined 14 |
| P06 | Limit increase (out of scope) → abstain, offer a human | `CLI-PV0OIEA8DAAE` Juliana Contreras Medina, MX, Student | Card `PRD-QM9G50SHLSY4` (1137), 120 days past due |
| P07 | Suspected fraud → block, read-back, dispute | `CLI-EX6BOAOEFZHQ` Marco Torres García, MX, Basic | `TRX-23BIJAU4GL46ATPW9STY` 05-31 06:09 Estación de Servicio USD 288.69, Approved, `fraud_score` 62, card 4497 (second card 4391) |
| P08 | Open unrecognized-charge case → follow-up, hand-off | `CLI-GG3Z1440277M` Guillermo Salazar Suárez, CO, Premium | `CMP-FHCLR8TGWMBD0YFOCLYS` In Process since 06-08; `TRX-OW0S5SQC8JI9MJDLTKU1` 06-17 Super Ahorro COP 1,551,223 |
| P09 | Records contradict → hand-off offer | `CLI-UBR2NCZWTD4K` Leonardo Vega Suárez, AR, Basic | `TRX-RX1ENVJQ5J26GXX7T8F7` 05-28 Cable TV USD 41.11, Declined 54, on card 4510, which is valid until 2029-06-25 and was not reissued |
| P10 | Card not active → status only, offer a human | `CLI-Z3V3SBS18YWQ` Luz Castro González, MX, Basic | Card `PRD-AK4W4IPVS8N8` (7718) Blocked; card 2626 Active, used 06-17 |

The persona file also holds alternates: P01 `CLI-S2QIJKEZV442`; P07 `CLI-HTX9ITCO0IMR`. Each entry records `use_case`, `expected_outcome` and `evidence` (row IDs). The process doc carries the full rows.

## 7. Defect cohort

### 7.1 Classes

Every class is computed on the **clean** values, before the C-rules. "30 d" means `process_date > as_of − 30 days`. The candidates column counts raw customers with card activity in the last 30 days.

| Class | Defect (diagnostic ID) | Definition | Candidates |
|---|---|---|---:|
| K01 | Customer not Active, still buying (D07) | `customer_status <> 'Active'` | 4,773 |
| K02 | Active card past expiry, approvals after it (D09) | Approved card tx in 30 d with `transaction_date > expiration_date` on an Active card | 15,396 |
| K03 | Incomplete Active credit card (D10) | Active credit card with `credit_limit` or `expiration_date` `NULL` | 3,736 |
| K04 | Over-limit Active credit card (D10) | `current_balance > credit_limit` | 458 |
| K05 | Stale Pending (D19) | Card tx Pending with `process_date ≤ as_of − 30 d` | 10,923 |
| K06 | Pending/Reversed with a decline code (D17) | In 30 d | 1,270 |
| K07 | Code 54 on a non-expired card (D18) | Declined `'54'` in 30 d, `expiration_date ≥ transaction_date` | 235 |
| K08 | Declined/Approved with no code (D17) | In 30 d | 2,070 |
| K09 | `'Mexico'` spelling (D21) | Card tx in 30 d | 388 |
| K10 | No `amount_usd` on ARS/COP (D24) | Card tx in 30 d | 946 |
| K11 | Purchase without merchant or category (D20) | Card tx in 30 d | 2,827 |
| K12 | Case open over 60 days (D26) | Open/In Process/Escalated, no `closing_date`, created < as_of − 60 d | 8,995 |
| K13 | Resolved case with no `closing_date` (D26) | — | 2,904 |
| K14 | Case money in a foreign currency (D28) | `claimed_amount` not `NULL` and `currency` ≠ home currency | 3,437 |
| K15 | Dates after as_of (D04, D27) | Case lifecycle date or `customers.last_updated` > as_of | 2,113 |
| K16 | Minor at registration (D03) | Age < 18 at `registration_date` | 1,578 |
| K17 | Missing email or mobile (D06) | — | 1,639 |

### 7.2 Selection

1. Candidates: customers with ≥ 1 card transaction in 30 d (any card status), not personas.
2. Classes are filled from the rarest to the most common, by candidate count. Each class takes top-scored candidates (score from 6.2 computed on clean values; ties by `md5(customer_id)`) until it has `--defect-per-class` members (default 20). A customer already selected counts toward every class it carries.
3. The pinned total is 159 customers (at most 17 × 20 = 340): 145 of them carry two or more classes.
4. A class with fewer candidates than its target takes all of them; the shortfall is recorded.
5. The clean selection (6.3) then excludes every cohort customer.

### 7.3 Output and records

- Cohort customers' rows in customers, products, transactions and complaints come from the snapshot taken before the C-rules. Their rows in the other five customer-linked tables (interactions, transcripts, surveys, digital events, campaign sends) are already unchanged by the rules.
- `curate.json` → `defects` records, per customer, its classes and the **evidence row IDs** that triggered each class (transaction, product or complaint IDs). The evaluation harness labels cases from these.
- The agent's expected behaviour per class is a `POLICY.md` decision in the harness spec, not here. Examples: never call an expired card active; say "the records don't match" on K07; decide whether to serve a Closed customer on K01. The process doc lists draft expectations as open items.

## 8. Checks (the stage fails on any)

| Check | Scope |
|---|---|
| Evidence preconditions (4.2 step 2) | All rows |
| Each C-rule count equals `expected.json` → `curation.rules` (full runs only) | All rows |
| Each C-rule invariant (5.1, 5.2) | Clean customers' output rows |
| G1–G8 hold for every selected clean customer; every persona is selected | Clean customers |
| Every cohort customer still carries each of its classes in the output | Cohort |
| `repair.check_links`: 24 links, ownership, dates | Whole curated output |
| Clean and cohort sets are disjoint; no `EVL-` ID | Whole output |
| Rule counts and rows per table equal `expected.json` → `curation` (full runs, default sizes). Rows per table change whenever the selection or the cohort changes, so per-cell and per-class counts are not pinned separately; they stay in `curate.json` | Whole output |

## 9. Run record: `runs/<run-id>/curate.json`

```json
{
  "run_id": "…",
  "as_of": "2026-06-17T23:59:59",
  "rules": {"C1": {"changed": 40515}, "C8": {"reissued": 51493, "kept_expired": 5171}, "…": {}},
  "selection": {
    "funnel": {"G1": 127700, "…": 0, "eligible": 15122},
    "cells": {"Argentina|Basic": {"eligible": 1789, "selected": 125}, "…": {}},
    "personas": {"P01": {"customer_id": "CLI-1GL7QBDG3QG0", "gates": "pass"}, "…": {}},
    "scenarios": {"decline_7d": 0, "…": 0}
  },
  "defects": {
    "classes": {"K07": {"candidates": 235, "selected": 20}, "…": {}},
    "customers": {"CLI-…": {"K02": ["TRX-…"], "K12": ["CMP-…"]}}
  },
  "tables": {"customers": {"rows": 0, "uri": "s3://…/curated/<run-id>/customers.parquet", "sha256": "…"}}
}
```

`runrecord.STAGES` gains `"curate"`. The record is cleared when the stage starts, as for the other stages.

## 10. Components

| Path | Change |
|---|---|
| `data_load/curate.py` | New: evidence checks, C1–C12 (each rule a function with a temp fix table, as in `repair.py`), defect classes and snapshot, gates, score, allocation, filtering, checks, Parquet writing (reuses `transform._write` and `sha256_file`) |
| `data_load/personas.json` | New: the 10 personas and their alternates (6.4) |
| `data_load/__main__.py` | New `curate` command (`--source`, `--out`, `--customers 1500`, `--defect-per-class 20`); `load` reads `curate.json` |
| `data_load/runrecord.py` | `STAGES` + `"curate"` |
| `data_load/expected.json` | New `curation` block, pinned by the rehearsal |
| `infra-cdk/lib/data-construct.ts` | `stage("Curate")` between Transform and Load; CodeBuild description lists the four stages |
| `infra-cdk/test/data-construct.test.ts` | State order Ingest → Transform → Curate → Load → ReadCheck |
| `tests/unit/test_data_load_curate.py` | New (section 11) |
| `tests/unit/test_data_load_cli.py`, `test_data_load_runrecord.py` | `curate` command, load reading `curate.json`, the new stage name |
| Tools, `schema.sql`, `dsql.py`, read check | Unchanged |

## 11. Testing

**Unit tests** (no AWS; tiny hand-built tables, as in `tests/unit/test_data_load_repair.py`):

- **One test per C-rule with its edge case:**
  - C2 on a half-cent value (Python rounding, not DuckDB's);
  - C7 rolling a Closed-in-the-future case back to In Process;
  - C8 reissuing a card and keeping one with code-54 evidence;
  - C11 with each country's deadline, a Rejected case, and a case still inside its deadline;
  - C12 converting COP and leaving `NULL` when there is no amount.
- **Gates:** each gate with a passing and a failing customer.
- **Allocation:** equal cells, a short cell recorded as a shortfall, ties broken by MD5, and the same input giving the same selection twice.
- **Personas:** a persona failing a gate fails the stage, naming both.
- **Defect cohort:**
  - classes filled from the rarest, with multi-class counting;
  - cohort rows keep their raw values while clean customers get fixed values;
  - the "defect survived" check fails when a cohort row is altered.
- **Subset filtering:** transcripts and surveys follow their interaction; anonymous digital events are dropped; `check_links` passes on the output.
- **Plumbing:** the CLI `curate --source` writes the 13 Parquet files; `load` reads `curate.json` (fake S3) and fails without it.

**CDK test:** the five states in order.

**Local rehearsal** on the full data:

```bash
python -m data_load transform --source datathon/data --out <tmp>              # ~7 min, already reproduces R1–R6
python -m data_load curate --source <tmp> --out <tmp2>                         # pins expected.json → curation
```

## 12. Failure handling

| Failure | Behaviour |
|---|---|
| An evidence check, rule count, invariant, gate, persona, cohort, link or count check fails | The stage fails, naming the check; DSQL is untouched |
| A cell or class is short of its target | Recorded in `curate.json`; the stage passes |
| Load runs before curate | It fails with "run curate first" |
| The selection needs retuning | Rerun `curate` and then `load` for the same run (~5 min); transform is not rerun |

## 13. Cost and duration

| Item | Estimate |
|---|---|
| Curate on CodeBuild `arm1.large` | ~3 min (download 1.2 GB, ~2 min of DuckDB) ≈ $0.05 |
| Load | From ~24 min to ~2 min for 1,659 customers and 270,866 rows. DSQL write DPU drops by ~95% (≈ $0.15 instead of ≈ $2.97 per run) |
| Storage | From ~6.6 GB to well under 1 GB, inside the free tier |

The endpoint ($7.30/month) still dominates the monthly cost.

## 14. Documentation (written after the rehearsal)

1. **This spec.** Pinned counts are added after the rehearsal.
2. **`datathon/docs/analysis/2026-10-03-curated-customers.md`**, covering:
   - the full process (diagnostic → rules → gates → selection → defect cohort) with exact counts;
   - the 10 personas with full rows and the reason for each pick, plus alternates;
   - one showcase customer per defect class with its evidence rows and a draft expected behaviour;
   - reproduction commands.
3. **Updates to existing docs:**
   - `datathon/docs/analysis/2026-10-02-agent-data-diagnostic.md`: §8 decisions marked resolved, plus D38 and D39;
   - the README pipeline section (five stages);
   - `docs/superpowers/specs/2026-10-02-data-pipeline-design.md`: a note that load reads `curated/` (this spec).

## 15. Out of scope

- The evaluation harness: `POLICY.md`, label functions, mutation ops and `EVL-` clones, the case generator, graders, AgentCore Evaluations. It is the next sub-project.
- The agent-side requirements the harness research raised: a terminal disposition per conversation, and sandboxed write tools.
- Cognito user mapping for the personas (`USER_CUSTOMER_IDS_MAP`); the persona file is its input.
- Raw links for the cohort (E9), and any change to the tools.

## 16. Open items

1. **C11 is approximate:** business-day deadlines are converted to calendar days (×7/5, rounded). An exact business-day calendar per country is deferred.
2. **The score is a draft:** its weights are not tuned. It ranks within a cell and doesn't decide eligibility.
3. **Cohort size:** resolved by the rehearsal: 159 customers, because most carry several classes.
