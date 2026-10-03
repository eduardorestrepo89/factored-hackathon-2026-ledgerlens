# Curated customers: process, rules, personas and defect cohort

Factored AI & Data Hackathon 2026 · 2026-10-03 · `as_of` 2026-06-17 · spec `docs/superpowers/specs/2026-10-03-curate-stage-design.md`

## 1. Why this exists

**The problem.** The data pipeline loads all 23,495,188 rows and repairs the broken links (R1–R6). But the agent talks to one customer at a time, and one customer's rows contradict each other:
- Active cards past their expiry keep approving purchases.
- Pending charges never settle: their median age is 547 days.
- Cases stay open for about 545 days.
- Closed customers keep buying.
- 85% of `last_transaction_date` values are wrong.

Activity is also thin: about 97% of customers have no card charge in the last 3 days. [`2026-10-02-agent-data-diagnostic.md`](2026-10-02-agent-data-diagnostic.md) measures all of it, defects D01–D39.

**The curate stage,** between transform and load, does three things:
1. **Fixes what a rule can fix honestly.** Rules C1–C12: seven derive values from other columns, and five are synthetic rules, labelled as such.
2. **Selects 1,500 coherent customers,** spread evenly over the 12 country × segment cells. Ten of them are pinned personas, one per use case.
3. **Keeps 159 incoherent customers exactly as transform wrote them.** This is the defect cohort, so the agent can also be tested on bad data.

**What changes for the agent:** the tools don't change. DSQL `public` holds 1,659 customers and 270,866 rows instead of 23.5M. S3 `clean/` keeps the full repaired data for lineage and analysis.

## 2. The process, step by step

1. **Load:** the 13 clean Parquet tables (23,495,188 rows) go into an on-disk DuckDB.
2. **Evidence checks:**
   - every named merchant has exactly one category;
   - `usd()` reproduces all 1,887,552 stored `amount_usd` values;
   - no customer ID uses the reserved `EVL-` prefix.
3. **Defect cohort:**
   - the 17 classes are computed on the clean values;
   - 159 customers are selected, 20 per class, filling the rarest class first and counting overlaps;
   - their customers, products, transactions and complaints rows are snapshotted.
4. **Rules C1–C12** run over all rows (section 3).
5. **Gates and selection:** 14,999 customers pass gates G1–G8, and 125 per cell are taken, personas first, giving 1,500.
6. **Assembly:**
   - the clean and cohort customers are kept;
   - the cohort's rule-table rows come from the snapshot;
   - transcripts and surveys follow their interaction;
   - anonymous digital events are dropped;
   - dimension tables go in whole.
7. **Checks and output:**
   - rule invariants on the clean customers;
   - every gate re-checked on the output;
   - every cohort customer still carries its defects;
   - the 24 link checks;
   - the pinned counts in `data_load/expected.json` → `curation`.
   Then 13 Parquet files and `curate.json` are written.

To reproduce, from the repo root:

```bash
uv run --no-project --quiet --with-requirements data_load/requirements.txt python -m data_load transform --source datathon/data --out <tmp>/clean
uv run --no-project --quiet --with-requirements data_load/requirements.txt python -m data_load curate --source <tmp>/clean --out <tmp>/curated
uv run --no-project --quiet --with duckdb==1.5.5 python datathon/analysis/curated_customers.py <tmp>/curated
```

On a laptop, the transform takes about 7 minutes and curate about 4. The last command prints the tables in sections 4–6 of this document.

## 3. Rules applied

| Rule | Class | Change | Rows | Evidence |
|---|---|---|---:|---|
| C1 | Derive | `transaction_country` `'Mexico'` → `'México'` | 40,515 | Same Mexican cities under both spellings (D21) |
| C2 | Derive | Missing `amount_usd` on ARS/COP → Python `round(amount/350 or /4000, 2)` | 99,477 | Reproduces all 1,887,552 stored values (D24) |
| C3 | Derive | Missing `merchant_category` → the merchant's only category | 51,952 | 24 merchants, one category each (D20) |
| C4 | Derive | Approved with no `response_code` → `'00'` | 203,369 | `'00'` is the only code on 3.87M Approved rows (D17) |
| C5 | Derive | `last_transaction_date` → the product's real last transaction | 339,965 | D11 |
| C6 | Derive | `last_updated` after `as_of` → `as_of` | 9,316 customers + 25,113 products | D04 |
| C7 | Derive | Case lifecycle dates after `as_of` → the case's state at `as_of` | 283 | D27 |
| C8 | Synthetic | Active card expired at `as_of` → reissued: expiry plus its own 3–5-year term, until after `as_of` | 51,493 reissued; 5,171 kept | D09 |
| C9 | Synthetic | Pending for 7 days or more → Approved `'00'` (the authorization settled) | 87,740 | D19 |
| C10 | Synthetic | Decline code on Pending/Reversed → `NULL` | 43,006 | D17 |
| C11 | Synthetic | Case past its legal answer deadline (AR 14, CO 21, MX 42 days) → Closed on that day; Rejected cases get the closing date | 48,943 closed; 685 Rejected dated | D26 |
| C12 | Synthetic | Case money → the customer's home currency, at the book rate | 23,299 | D28 |

**C8's exception (spec decision E5).**
- **The problem:** a blanket reissue would have turned 239 of the 510 code-54 ("expired card") declines from the last 30 days into false contradictions, because those cards really were expired on the decline date.
- **The rule:** a card with a code-54 decline after its original expiry keeps that expiry (5,171 cards), and gate G7 keeps its holders out of the clean set.
- **The rejected alternative:** filtering out every expired card instead would have cut the rare scenarios by about two thirds.

**C12 converts amounts (spec decision E6).**
- **The problem:** case amounts don't scale with their currency; the median is about 2,500 in ARS, COP, MXN and USD alike. Changing only the currency would make the agent quote "COP 2,467", about USD 0.62.
- **The rule:** amounts are treated as USD and converted at the book rate.
- **What it counts:** only rows whose values change. Mexican cases already in USD aren't counted.

**Kept as delivered, with a label:**
- D01: Mexican identity formats.
- D12: Mexico in USD.
- D13: card numbers fail the Luhn check.
- D14: mortgages over their limit.
- D18: remaining code contradictions; the explain tool flags them.
- D20: channel and type oddities (ATM purchases, POS withdrawals).
- D22: uniform amounts and hours.
- D23: `fraud_score` leaks the fraud label.
- D30–D34: template text, contacts and agents.
- D38: segment is unrelated to age; Students have a median age of 52.
- D39: event types don't match page titles ("Login" on "Cerrar Sesión").

**Tried and rejected:** computing C2 with a DuckDB Python function. It needs numpy and ran about 600× slower: 95 s per 200,000 rows, against 0.15 s in plain Python.

## 4. Selection

| Gate | Rule | Customers passing all gates so far |
|---|---|---:|
| G1 | `customer_status = 'Active'` | 127,700 |
| G2 | 18 or older at `registration_date` | 121,256 |
| G3 | Email and mobile present | 115,174 |
| G4 | Clean first name: no repeated token, no male + female compound | 108,888 |
| G5 | At least one usable credit card: Active, not expired, with a limit, not over it | 41,648 |
| G6 | Every Active card has an expiry; every Active credit card has a limit | 38,928 |
| G7 | No Active card expired at `as_of` | 37,696 |
| G8 | A card transaction on a usable card in the last 30 days | 14,999 |

**Score (draft weights).** It ranks customers within a cell and decides nothing about eligibility:

```text
score = 3·min(card tx in 30 d on usable cards, 5)
      + 2·[decline 05/14/51 in 7 d] + 2·[Pending in 7 d] + 2·[Reversed in 30 d] + 3·[fraud_score > 30, Approved, in 30 d]
      + 2·[open unrecognized-charge case] + [code-54 decline in 30 d] + [foreign charge in 30 d]
      + [digital event in 24 h] + [call in 90 d] + [≥ 2 usable cards] + [Blocked/Suspended credit card] + [past-due usable credit card]
```

| Cell | Eligible | Selected |
|---|---:|---:|
| Argentina × Basic | 1,764 | 125 |
| Argentina × Plus | 736 | 125 |
| Argentina × Premium | 330 | 125 |
| Argentina × Student | 154 | 125 |
| Colombia × Basic | 2,656 | 125 |
| Colombia × Plus | 1,135 | 125 |
| Colombia × Premium | 439 | 125 |
| Colombia × Student | 219 | 125 |
| México × Basic | 4,572 | 125 |
| México × Plus | 1,851 | 125 |
| México × Premium | 743 | 125 |
| México × Student | 342 | 125 |

**Why equal cells (spec decision E7).** Proportional allocation would give Argentina × Student about 15 customers. Equal cells give every language and segment stratum enough customers to report on.

**Scenarios in the 1,500.** These are for information only; the evaluation harness injects rare situations into `EVL-` clones:

| Scenario | Customers |
|---|---:|
| Two or more usable cards | 1,224 |
| Past-due usable credit card | 467 |
| Foreign card charge in 30 days | 216 |
| Blocked or Suspended credit card | 102 |
| Reversed charge in 30 days | 61 |
| Decline (05/14/51) in 7 days | 55 |
| Pending charge in 7 days | 30 |
| Code-54 decline in 30 days | 25 |
| Digital event in 24 hours | 17 |
| Open unrecognized-charge case | 7 |
| Fraud-flagged approved charge in 30 days | 3 |

## 5. The 10 personas

Every persona has an evidence row inside the window the tools read: a credit-card Purchase with a merchant, on POS, App or Web. Personas are pinned in `data_load/personas.json`; if one stops passing a gate, the stage fails, naming it.

| # | Use case → expected outcome | Customer | Country, segment | Why this one |
|---|---|---|---|---|
| P01 | Decline explained → exit 1 | `CLI-1GL7QBDG3QG0` Rocío Isabel López García, F, 60 | Colombia, Plus | The code-51 decline is in the 72-hour window, so the session opens with it. One card, so no ambiguity. Available credit today is USD 11,244, which tests "state what the code means, never guess the cause" |
| P02 | Pending charge → exit 1 | `CLI-7EC6UCDZMSKV` Martín Romero Fernández, M, 30 | Argentina, Basic | Pending in the 72-hour window. After C9, "pending" really means recent. Two Active credit cards |
| P03 | Reversed charge with app context → exit 1 | `CLI-70U0WJ1NH1MN` Laura Acosta Acosta, F, 57 | Argentina, Plus | The "where is my refund?" case. Her app view of "Tarjeta de Crédito" makes her the only persona whose session gets a digital signal |
| P04 | Which card? → clarify | `CLI-N4FPJIEGD917` Óscar Diego Gutiérrez Rodríguez, M, 26 | Colombia, Plus | Mercado Central on two cards in two currencies, so the agent must ask. Highest score in the pool |
| P05 | Portuguese persona, foreign charge | `CLI-50OIF5EIYSWK` Alejandro Torres Ortiz, O, 28 | México, Plus | A Brazilian charge in the 72-hour window (the foreign flag) and a code-14 decline: two attention items |
| P06 | Limit increase (out of scope) → abstain, offer a human | `CLI-PV0OIEA8DAAE` Juliana Contreras Medina, F, 34 | México, Student | A card 120 days past due gives read-only servicing facts. The only Student |
| P07 | Suspected fraud → block, read-back, dispute | `CLI-EX6BOAOEFZHQ` Marco Torres García, M, 72 | México, Basic | An approved charge with fraud score 62. His second card tests that the block targets card 4497 only |
| P08 | Open unrecognized-charge case → follow-up, hand-off | `CLI-GG3Z1440277M` Guillermo Salazar Suárez, M, 32 | Colombia, Premium | A real open case inside Colombia's 21-day deadline: follow it up, don't file a duplicate. The only Premium |
| P09 | Records contradict → hand-off offer | `CLI-UBR2NCZWTD4K` Leonardo Vega Suárez, O, 82 | Argentina, Basic | A code-54 ("expired card") decline on a card valid until 2029. The contradiction is in the delivered data; C8 didn't create it. The oldest persona |
| P10 | Card not active → status only, offer a human | `CLI-Z3V3SBS18YWQ` Luz Castro González, F, 83 | México, Basic | A Blocked card next to an Active past-due one. The data holds no block reason or date, so the agent can't invent one |

**Spread:**
- **Case types:** 3 normal, 3 ambiguous or unsupported, 4 human-required.
- **Countries:** Colombia 3, Argentina 3, México 4.
- **Segments:** Basic 4, Plus 4, Premium 1, Student 1.
- **Gender and age:** F 4, M 4, O 2; ages 26–83.

**Alternates:** P01 `CLI-S2QIJKEZV442`, P07 `CLI-HTX9ITCO0IMR`.

**Weaknesses kept on purpose:**
- Laura's surname repeats.
- Marco's flagged gas-station charge came in through the Web channel.
- Óscar Diego's and Luz's past-due cards still get approvals (D20, D22).

### P01: Decline explained

Expected: exit 1: explain the code's meaning from the record; no cause guessed. Evidence: TRX-SSJAIUCVVU1L4605ZLNM, PRD-GKI6NTZU2AEX.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-1GL7QBDG3QG0 | Rocío Isabel | López García | F | Colombia | Barranquilla | Plus | Active | 60 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-GKI6NTZU2AEX | 6811 | Tarjeta Crédito | Active | USD | 860.65 | 12105.00 | 2028-04-04 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-SSJAIUCVVU1L4605ZLNM | 2026-06-17 18:25:07 | 6811 | Purchase | Restaurante El Buen Sabor | 128.30 | USD | Colombia | POS | Declined | 51 |  |

Cases, last 120 days:

_none_

### P02: Pending charge

Expected: exit 1: explain that the charge is pending. Evidence: TRX-M8SV89D2QGIE6WRUB79K, PRD-1CF5T9HNCQ1X.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-7EC6UCDZMSKV | Martín | Romero Fernández | M | Argentina | La Plata | Basic | Active | 30 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-1CF5T9HNCQ1X | 2196 | Tarjeta Crédito | Active | ARS | 609725.19 | 12575007.13 | 2027-05-09 | 0 |
| PRD-93NP4K8JRI7E | 3354 | Tarjeta Crédito | Active | ARS | 420169.04 | 14774438.61 | 2029-02-16 |  |
| PRD-KZRM0F6AKUES | 4364 | Tarjeta Crédito | Closed | ARS | 886914.20 | 14811201.21 | 2027-04-30 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-M8SV89D2QGIE6WRUB79K | 2026-06-17 20:07:20 | 2196 | Purchase | Farmacia Salud | 125356.26 | ARS | Argentina | Web | Pending |  | 25.20 |
| TRX-N0ZNMHNQQSPUXAV3C6M6 | 2026-06-13 03:30:30 | 3354 | Purchase | Cable TV | 149632.86 | ARS | Argentina | Branch | Approved | 00 | 29.42 |

Cases, last 120 days:

_none_

### P03: Reversed charge with app context

Expected: exit 1: explain the reversal; session opens with the app signal. Evidence: TRX-LJGEBUAOX0G4CL4RQSIU, PRD-UUY4Z9TDEF96.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-70U0WJ1NH1MN | Laura | Acosta Acosta | F | Argentina | La Plata | Plus | Active | 57 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-OL2UL7987ML1 | 5258 | Tarjeta Crédito | Active | ARS | 56940.90 | 11653556.24 | 2028-07-31 | 0 |
| PRD-UUY4Z9TDEF96 | 8910 | Tarjeta Crédito | Active | ARS | 741526.16 | 9066164.42 | 2029-01-22 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-LJGEBUAOX0G4CL4RQSIU | 2026-06-16 03:33:45 | 8910 | Purchase | Laboratorio Central | 129811.06 | ARS | Argentina | App | Reversed |  | 7.04 |

Cases, last 120 days:

_none_

### P04: Which card?

Expected: clarify which card before anything else. Evidence: TRX-19B2TR7A8QXK7243KZV6, TRX-9TDT782N9PARVY8IMPRE, PRD-TVC3HHMH0II0, PRD-VLRZ7201XLV1.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-N4FPJIEGD917 | Óscar Diego | Gutiérrez Rodríguez | M | Colombia | Medellín | Plus | Active | 26 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-BMAA6ZWGN0SM | 8225 | Tarjeta Débito | Blocked | COP | 4683153.99 |  | 2024-02-01 |  |
| PRD-NLMWWXUUY6LK | 3634 | Tarjeta Débito | Active | COP | 777146.62 |  | 2027-04-06 |  |
| PRD-TVC3HHMH0II0 | 2218 | Tarjeta Crédito | Active | USD | 812.44 | 25073.69 | 2027-02-14 | 120 |
| PRD-VLRZ7201XLV1 | 5384 | Tarjeta Crédito | Active | COP | 8379694.63 | 92000259.54 | 2029-04-17 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-A1GUNA80TFJC2OKF9JSF | 2026-06-17 08:52:25 | 5384 | Payment |  | 2695397.83 | COP | Colombia | ATM | Approved | 00 | 16.87 |
| TRX-OY33SNPTNSAI0C897QG3 | 2026-06-16 10:21:23 | 2218 | Purchase | Empresa Telefónica | 443.11 | USD | Colombia | POS | Approved | 00 | 23.91 |
| TRX-19B2TR7A8QXK7243KZV6 | 2026-06-14 11:56:32 | 2218 | Purchase | Mercado Central | 74.52 | USD | Colombia | ATM | Pending |  | 20.89 |
| TRX-09Q8YDJWYQ433RI0H5MW | 2026-06-09 01:22:15 | 2218 | Purchase | Conciertos Live | 91.44 | USD | Colombia | POS | Approved | 00 | 29.08 |
| TRX-6AIFHLIO1HS9IARF1TVB | 2026-06-03 08:02:47 | 2218 | Purchase | Super Ahorro | 178.57 | USD | Colombia | Branch | Approved | 00 |  |
| TRX-9TDT782N9PARVY8IMPRE | 2026-05-28 22:40:37 | 5384 | Purchase | Mercado Central | 1973645.12 | COP | Colombia | Web | Approved | 00 |  |

Cases, last 120 days:

| complaint_id | creation_date | category | subcategory | status | claimed_amount | currency | closing_date |
|---|---|---|---|---|---|---|---|
| CMP-ITH8V9HEMQSIWWQHWW69 | 2026-04-05 14:37:39 | Branch | Atención en sucursal | Closed | 8120360.00 | COP | 2026-04-26 14:37:39 |

### P05: Portuguese persona, foreign charge

Expected: answer in Portuguese; explain the charge in Brazil. Evidence: TRX-MQKFELIPWT098DXTN2WN, TRX-YLR3CXW0CFHFUNT2IUWZ, PRD-MTDX0544YHDL.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-50OIF5EIYSWK | Alejandro | Torres Ortiz | O | México | Puebla | Plus | Active | 28 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-JM7RHA6PVW6X | 5615 | Tarjeta Débito | Active | USD | 509.94 |  | 2028-09-20 |  |
| PRD-MTDX0544YHDL | 2057 | Tarjeta Crédito | Active | USD | 545.66 | 10512.82 | 2028-11-08 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-MQKFELIPWT098DXTN2WN | 2026-06-17 13:29:12 | 2057 | Purchase | Super Ahorro | 128.67 | USD | Brazil | POS | Approved | 00 |  |
| TRX-YLR3CXW0CFHFUNT2IUWZ | 2026-06-14 16:03:07 | 2057 | Purchase | Ferretería | 88.17 | USD | México | POS | Declined | 14 | 13.95 |
| TRX-OSTJS00WV9937XM0MB5Q | 2026-05-25 00:07:11 | 5615 | Purchase | Cable TV | 82.89 | USD | México | ATM | Approved | 00 | 21.88 |

Cases, last 120 days:

_none_

### P06: Limit increase (out of scope)

Expected: abstain and offer a human; read-only servicing facts allowed. Evidence: PRD-QM9G50SHLSY4.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-PV0OIEA8DAAE | Juliana | Contreras Medina | F | México | Querétaro | Student | Active | 34 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-JPLWXHACX9UV | 3227 | Tarjeta Débito | Active | USD | 1069.47 |  | 2028-10-11 |  |
| PRD-K2A6QA5IGAL0 | 2168 | Tarjeta Crédito | Active | USD | 406.37 | 30740.20 | 2030-08-19 | 0 |
| PRD-QM9G50SHLSY4 | 1137 | Tarjeta Crédito | Active | USD | 1128.79 | 12526.07 | 2028-09-06 | 120 |
| PRD-SA8HWQBPR60S | 2481 | Tarjeta Crédito | Active | USD | 1453.19 | 10788.53 | 2027-03-17 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-7QQQT8XPL0V3FYPTL94Y | 2026-06-11 17:37:38 | 1137 | Payment |  | 1629.34 | USD | México | ATM | Approved | 00 |  |
| TRX-XKROSVHO8Y5W5GPZJ0TL | 2026-05-30 23:11:57 | 2168 | Purchase | Taxi Seguro | 11.66 | USD | México | POS | Approved | 00 | 21.54 |
| TRX-60P737BA987VY1FGOD1G | 2026-05-25 08:49:13 | 1137 | Payment |  | 1102.59 | USD | México | Web | Approved | 00 | 0.14 |
| TRX-9R57WBM4C92EHZCL21B4 | 2026-05-22 10:22:22 | 3227 | Purchase | Conciertos Live | 351.38 | USD | México | Branch | Approved | 00 | 26.31 |
| TRX-XIMXWDXALLZ536UHE5Q3 | 2026-05-19 11:50:36 | 2481 | Purchase | Super Ahorro | 428.78 | USD | México | POS | Approved | 00 |  |

Cases, last 120 days:

_none_

### P07: Suspected fraud

Expected: exit 2 then 3: confirm, block card 4497, read back, dispute intake. Evidence: TRX-23BIJAU4GL46ATPW9STY, PRD-Z3Y8BK8CKUTN.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-EX6BOAOEFZHQ | Marco | Torres García | M | México | Ciudad de México | Basic | Active | 72 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-I7CW038INJHY | 4391 | Tarjeta Crédito | Active | USD | 852.12 | 20098.75 | 2027-03-04 | 0 |
| PRD-Z3Y8BK8CKUTN | 4497 | Tarjeta Crédito | Active | USD | 1497.29 | 14519.13 | 2029-06-26 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-GQLHRNO8BSQEL5CYFBIQ | 2026-06-17 19:28:26 | 4497 | Withdrawal |  | 31.16 | USD | México | Web | Approved | 00 | 25.02 |
| TRX-FCU25RX5NHGFRTWKVXLI | 2026-06-11 19:14:09 | 4497 | Purchase | Tienda General | 28.40 | USD | México | ATM | Approved | 00 |  |
| TRX-5QIF7WXF3DY0D8F26PMX | 2026-06-05 02:05:49 | 4391 | Purchase | Óptica Visión | 383.72 | USD | México | App | Approved | 00 | 27.91 |
| TRX-23BIJAU4GL46ATPW9STY | 2026-05-31 06:09:15 | 4497 | Purchase | Estación de Servicio | 288.69 | USD | México | Web | Approved | 00 | 62.39 |

Cases, last 120 days:

_none_

### P08: Open unrecognized-charge case

Expected: exit 3: follow up the open case, no duplicate; hand-off. Evidence: CMP-FHCLR8TGWMBD0YFOCLYS, TRX-OW0S5SQC8JI9MJDLTKU1.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-GG3Z1440277M | Guillermo | Salazar Suárez | M | Colombia | Cali | Premium | Active | 32 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-91WQPO82YRER | 3270 | Tarjeta Crédito | Active | COP | 8585496.14 | 195362505.70 | 2029-11-26 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-OW0S5SQC8JI9MJDLTKU1 | 2026-06-17 01:57:55 | 3270 | Purchase | Super Ahorro | 1551223.00 | COP | Colombia | POS | Approved | 00 | 16.59 |
| TRX-EXPS6IF5L6VSF41I6ZWM | 2026-06-08 21:47:15 | 3270 | Payment |  | 7289683.59 | COP | Colombia | ATM | Approved | 00 | 21.24 |
| TRX-XM6FC6E6AQHK0HETGEBO | 2026-05-26 13:40:26 | 3270 | Withdrawal |  | 1101267.80 | COP | Colombia | ATM | Approved | 00 | 16.86 |

Cases, last 120 days:

| complaint_id | creation_date | category | subcategory | status | claimed_amount | currency | closing_date |
|---|---|---|---|---|---|---|---|
| CMP-FHCLR8TGWMBD0YFOCLYS | 2026-06-08 13:05:44 | Transactions | Cargo no reconocido | In Process |  |  |  |

### P09: Records contradict

Expected: say the records don't match (code 54 on a valid card); offer a hand-off. Evidence: TRX-RX1ENVJQ5J26GXX7T8F7, PRD-0Z61E1KSEEMC.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-UBR2NCZWTD4K | Leonardo | Vega Suárez | O | Argentina | Buenos Aires | Basic | Active | 82 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-0Z61E1KSEEMC | 4510 | Tarjeta Crédito | Active | USD | 1788.68 | 13785.22 | 2029-06-25 | 0 |
| PRD-DKS17GVIFCUI | 9979 | Tarjeta Débito | Active | ARS | 397655.53 |  | 2028-07-12 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-RX1ENVJQ5J26GXX7T8F7 | 2026-05-28 15:32:48 | 4510 | Purchase | Cable TV | 41.11 | USD | Argentina | App | Declined | 54 | 20.72 |
| TRX-UG31X6EC6QW2UMJTNP0S | 2026-05-26 11:15:02 | 4510 | Withdrawal |  | 299.87 | USD | México | ATM | Approved | 00 | 24.73 |
| TRX-QPI1UBGAYGDWOHTBEBWY | 2026-05-23 18:26:06 | 4510 | Payment |  | 1444.75 | USD | Argentina | Web | Approved | 00 | 1.56 |

Cases, last 120 days:

_none_

### P10: Card not active

Expected: state the Blocked status only (no reason in the data); offer a human. Evidence: PRD-AK4W4IPVS8N8.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-Z3V3SBS18YWQ | Luz | Castro González | F | México | Monterrey | Basic | Active | 83 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-3QW0JAT01Y7O | 2626 | Tarjeta Crédito | Active | USD | 1774.87 | 4443.04 | 2028-10-14 | 180 |
| PRD-AK4W4IPVS8N8 | 7718 | Tarjeta Crédito | Blocked | USD | 2180.08 | 22503.36 | 2030-11-25 | 0 |
| PRD-HR07TY8I65AK | 3515 | Tarjeta Débito | Active | USD | 622.54 |  | 2028-10-21 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-LIJ8JL7CMEVPE0NCNCY0 | 2026-06-17 22:11:26 | 2626 | Payment |  | 449.86 | USD | México | App | Approved | 00 | 18.32 |
| TRX-ME0QYHUG04CY35PH0GVZ | 2026-06-17 16:31:26 | 2626 | Withdrawal |  | 126.23 | USD | México | ATM | Approved | 00 | 27.86 |
| TRX-B730XX74OYUBVLMU34PN | 2026-06-10 12:50:19 | 2626 | Payment |  | 927.08 | USD | México | POS | Approved | 00 | 25.50 |
| TRX-8OHFDKDX45F4T0ES21S1 | 2026-05-23 10:18:26 | 2626 | Purchase | Uber | 118.13 | USD | México | Web | Approved | 00 | 25.71 |

Cases, last 120 days:

_none_

## 6. The defect cohort

**What it is.** The defect cohort has 159 customers. Their customers, products, transactions and complaints rows are written exactly as transform left them: R1–R6 have repaired the links, and no C-rule has run. Each customer carries the evidence row IDs for each of its classes in `curate.json` → `defects`, so the evaluation harness can label cases from the records.

**Overlaps.** Most cohort customers carry several classes:

| Classes per customer | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Customers | 14 | 46 | 54 | 29 | 11 | 3 | 1 | 1 |

**Expected behaviour.** The column below is a draft and an open item. The final rules belong in `POLICY.md`, in the evaluation harness spec.

| Class | Defect | Candidates | Selected | Draft expected agent behaviour |
|---|---|---:|---:|---|
| K01 | Customer not Active, still buying | 4,773 | 31 | Policy decides whether to serve; never imply the account is Active |
| K02 | Active card past its expiry, approvals after it | 15,391 | 20 | Never call the card "active and valid" without stating its expiry; flag it |
| K03 | Active credit card with no limit or no expiry | 3,736 | 20 | Say the limit or expiry isn't on record; never compute available credit |
| K04 | Active credit card over its limit | 458 | 20 | State the balance and limit as recorded; report negative available credit, don't explain it |
| K05 | Pending charge older than 30 days | 10,919 | 66 | Say "pending since <date>"; offer a hand-off; never promise settlement |
| K06 | Pending or Reversed with a decline code | 1,267 | 28 | Report the status; flag `status_code_mismatch` |
| K07 | Code 54 on a card that isn't expired | 234 | 21 | Say the records don't match; offer a hand-off |
| K08 | Declined or Approved with no code | 2,068 | 26 | "Sin código registrado"; never guess a code |
| K09 | Country spelled `Mexico` | 385 | 20 | Treat it as México; never call a domestic purchase foreign |
| K10 | No USD amount on an ARS or COP charge | 946 | 20 | Omit the USD reference, or compute it at the book rate and say so |
| K11 | Purchase with no merchant or no category | 2,826 | 29 | Say the merchant isn't on record; ask the customer |
| K12 | Case open over 60 days | 8,992 | 66 | Report status and age; promise no date; offer escalation |
| K13 | Resolved case with no closing date | 2,904 | 21 | Report "resolved", not "open" |
| K14 | Case amount in a currency that isn't the customer's | 3,436 | 24 | Don't quote the amount as stored; flag it |
| K15 | Dates after `as_of` | 2,112 | 20 | Never mention future-dated facts |
| K16 | Minor at registration | 1,807 | 20 | Policy decides; most likely a hand-off |
| K17 | Missing email or mobile | 1,639 | 20 | A hand-off needs another contact channel; never invent one |

**Showcases.** Below is one customer per class, a different customer each time where possible, with the rows the agent's tools would read.

### K01: CLI-2H5M7846AJ1D

Evidence: CLI-2H5M7846AJ1D. All classes: K01, K10, K12.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-2H5M7846AJ1D | Antonio | Moreno Ramos | M | Argentina | Córdoba | Basic | Suspended | 61 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-D9V95RWORQ67 | 7811 | Tarjeta Crédito | Active | ARS | 374812.70 | 744984.80 | 2026-09-21 | 0 |
| PRD-GRRB098HXUYC | 4372 | Tarjeta Crédito | Active | USD | 284.88 | 8973.68 | 2031-02-13 | 0 |
| PRD-IP57E9DYVXME | 8042 | Tarjeta Débito | Active | USD | 1093.15 |  | 2031-01-22 |  |
| PRD-LDRKLSO2CAMV | 0796 | Tarjeta Crédito | Active | ARS | 585509.91 | 14054157.44 | 2029-07-14 | 0 |
| PRD-WO5PV1HYW0N1 | 3391 | Tarjeta Débito | Active | ARS | 428643.07 |  | 2027-05-02 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-PCA1K8EKBKY6ONOLVPXM | 2026-06-17 05:36:21 | 0796 | Purchase | Conciertos Live | 163870.71 | ARS | Argentina | Web | Approved | 00 | 5.87 |
| TRX-4J3OI0FYKVVSORLRIPBV | 2026-06-09 22:11:18 | 3391 | Purchase | Boutique Moda | 63508.01 | ARS | Argentina | POS | Approved | 00 | 18.22 |
| TRX-5LXTT5FZ41S5WN9OYEFX | 2026-05-23 22:11:14 | 3391 | Purchase | Farmacia Salud | 89110.62 | ARS | Argentina | POS | Approved | 00 | 1.48 |

Cases, last 120 days:

_none_

### K02: CLI-0IHHK5P7SSWR

Evidence: TRX-6M76DXB2WFDQT77J0QS3, TRX-CW4L9WPSE0LXF85DJ83E, TRX-YDKK2Z84X8TSYZTA9NCM. All classes: K02, K05, K09, K12.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-0IHHK5P7SSWR | Sebastián Miguel | Moreno Vargas | M | Argentina | Córdoba | Plus | Active | 43 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-2WM922N3XCFE | 2074 | Tarjeta Crédito | Active | USD | 1445.96 | 22449.47 | 2029-10-15 |  |
| PRD-CWNAR67XH9PD | 8992 | Tarjeta Débito | Active | ARS | 338979.49 |  | 2023-10-14 |  |
| PRD-J63P8GUL367X | 4415 | Tarjeta Crédito | Active | USD | 1024.13 | 49613.05 | 2027-06-08 | 0 |
| PRD-MB6BBNOWCILG | 1498 | Tarjeta Crédito | Active | ARS | 117849.52 | 1671481.60 | 2023-01-01 | 0 |
| PRD-ZUGR62TSGXAY | 6684 | Tarjeta Débito | Active | ARS | 474528.17 |  | 2024-09-11 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-CTQD9MRBYXZ4REPLZE2Z | 2026-06-15 00:41:49 | 4415 | Withdrawal |  | 90.38 | USD | Argentina | Web | Approved | 00 | 4.45 |
| TRX-YDKK2Z84X8TSYZTA9NCM | 2026-06-10 14:42:56 | 8992 | Purchase | Empresa Telefónica | 96910.78 | ARS | Argentina | POS | Approved | 00 | 4.12 |
| TRX-6M76DXB2WFDQT77J0QS3 | 2026-06-10 00:27:51 | 8992 | Withdrawal |  | 18882.97 | ARS | Argentina | POS | Approved | 00 |  |
| TRX-S1Q448AWCFJHMOOVSFTF | 2026-06-08 17:45:29 | 4415 | Payment |  | 1189.86 | USD | Argentina | ATM | Approved | 00 | 23.30 |
| TRX-0YQN9HYWO2LTRLWQ4ZS0 | 2026-05-24 14:06:35 | 2074 | Withdrawal |  | 113.78 | USD | Mexico | POS | Approved | 00 | 17.91 |
| TRX-QWZXT4QLSZE8QHU546DZ | 2026-05-22 12:33:24 | 4415 | Purchase | Cine Premium | 318.16 | USD | Argentina | ATM | Approved | 00 |  |
| TRX-CW4L9WPSE0LXF85DJ83E | 2026-05-19 09:44:30 | 1498 | Purchase | Servicios Públicos | 68669.20 | ARS | Argentina | ATM | Approved | 00 | 5.10 |

Cases, last 120 days:

_none_

### K03: CLI-0XWGQVG73DZK

Evidence: PRD-0A34N8UHZGJ8. All classes: K03, K05.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-0XWGQVG73DZK | Sofía | Alvarez Cortés | O | México | Ciudad de México | Plus | Active | 71 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-0A34N8UHZGJ8 | 1109 | Tarjeta Crédito | Active | USD | 1217.79 | 2376.24 |  | 0 |
| PRD-60NHAY4J6GK7 | 4963 | Tarjeta Débito | Active | USD | 496.78 |  | 2026-12-21 |  |
| PRD-79SBT65H6A4I | 6862 | Tarjeta Crédito | Active | USD | 2093.49 | 22597.22 | 2026-08-20 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-JYDGAQXJ5ZIS1XBW032P | 2026-06-16 17:23:31 | 6862 | Payment |  | 69.79 | USD | México | ATM | Declined | 14 |  |
| TRX-UN04UQ7RMFICH9V95XOE | 2026-06-09 20:33:44 | 4963 | Purchase | Streaming Music | 398.25 | USD | México | Web | Approved | 00 | 21.19 |
| TRX-BJ14OHGD44ZQJLJZLNJW | 2026-06-01 17:40:04 | 4963 | Purchase | Empresa Telefónica | 205.80 | USD | México | App | Approved | 00 | 2.98 |

Cases, last 120 days:

_none_

### K04: CLI-10T3UI3DKVK2

Evidence: PRD-YG9APD7LJXRX. All classes: K04, K12, K14.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-10T3UI3DKVK2 | Javier | Benítez Ruiz | M | Argentina | Rosario | Basic | Active | 27 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-CCSU6C44RI7T | 0123 | Tarjeta Crédito | Active | ARS | 577819.02 | 4092036.10 | 2029-12-24 | 0 |
| PRD-D0BPIH2WC3TP | 3631 | Tarjeta Débito | Active | ARS | 247704.86 |  | 2029-07-11 |  |
| PRD-I59EVVSP974J | 3001 | Tarjeta Débito | Active | USD | 543.28 |  | 2026-01-30 |  |
| PRD-U3BK35HI4WB6 | 5184 | Tarjeta Crédito | Active | ARS | 590952.73 | 7044613.68 | 2024-09-15 | 180 |
| PRD-YG9APD7LJXRX | 8934 | Tarjeta Crédito | Active | ARS | 755352.65 | 350532.42 | 2027-07-07 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-ZN5KTC8ICVK5NVDIHOOO | 2026-05-27 07:19:55 | 3631 | Purchase | Super Ahorro | 170098.60 | ARS | Argentina | Web | Approved | 00 |  |
| TRX-MIEHB2V8NIJ1DV6N2C87 | 2026-05-24 04:58:46 | 8934 | Purchase | Mercado Central | 97245.34 | ARS | Argentina | Web | Approved | 00 | 8.45 |

Cases, last 120 days:

_none_

### K05: CLI-0WWGTFVI9JX8

Evidence: TRX-8QRH6895IQZXZ34AT58M. All classes: K05, K06, K08, K17.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-0WWGTFVI9JX8 | Mauricio | Guerrero Vázquez | M | México | Querétaro | Basic | Active | 61 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-8XVXMFP2MDY2 | 2350 | Tarjeta Crédito | Active | USD | 474.86 | 26297.54 | 2027-06-30 | 0 |
| PRD-IYFKL885ZSDU | 6080 | Tarjeta Débito | Active | USD | 893.52 |  | 2026-10-14 |  |
| PRD-JC12D5N7KCQ9 | 6577 | Tarjeta Crédito | Active | USD | 1666.18 | 2373.66 | 2028-10-23 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-8OG4P48643L5MDBG9W0E | 2026-06-15 15:36:30 | 6577 | Payment |  | 56.75 | USD | México | POS | Pending | 14 | 1.12 |
| TRX-OZAHMONW97BTZKUOEXPV | 2026-05-25 11:15:24 | 6577 | Purchase | Streaming Music | 420.64 | USD | México | Transfer | Approved |  | 19.86 |
| TRX-J1AVVPM77JV5T8QSVHKH | 2026-05-24 23:02:13 | 6577 | Purchase | Cine Premium | 197.11 | USD | México | App | Approved | 00 | 25.79 |

Cases, last 120 days:

_none_

### K06: CLI-1NPM1EUEPIP0

Evidence: TRX-XN2E0O414RWYIG519D2E. All classes: K03, K05, K06, K07, K12.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-1NPM1EUEPIP0 | Susana | González Medina | O | México | Guadalajara | Basic | Active | 64 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-AWQ53L663JLA | 4443 | Tarjeta Débito | Active | USD | 384.67 |  | 2026-07-06 |  |
| PRD-FF6OR43YXX10 | 5378 | Tarjeta Crédito | Active | USD | 1436.93 |  |  | 180 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-6O968XK3D7P0767MR9MC | 2026-06-16 20:16:30 | 4443 | Payment |  | 1642.87 | USD | México | Web | Approved | 00 | 20.81 |
| TRX-XN2E0O414RWYIG519D2E | 2026-06-11 18:03:16 | 4443 | Purchase | Tienda Don José | 181.20 | USD | México | POS | Pending | 54 | 17.80 |
| TRX-TH2FGO5ZOCVNYQDSW738 | 2026-06-10 10:14:11 | 4443 | Purchase | Clínica Médica | 74.50 | USD | México | Web | Approved | 00 | 15.12 |
| TRX-BGJHHLRXSFMN784Z6KML | 2026-06-03 21:58:21 | 5378 | Payment |  | 1885.91 | USD | México | POS | Approved | 00 | 24.56 |
| TRX-PSU5L0Z4STHW3OVRPH3E | 2026-05-27 11:43:41 | 4443 | Purchase | Uber | 440.65 | USD | México | Web | Approved | 00 | 28.65 |
| TRX-YEDQVWYKV6141V2TH6E1 | 2026-05-20 17:27:40 | 4443 | Withdrawal |  | 321.93 | USD | México | POS | Declined | 54 | 11.35 |

Cases, last 120 days:

_none_

### K07: CLI-1PEJ6PRJFXOE

Evidence: TRX-1ASD0WXCOIHJPY31543Q. All classes: K07, K15.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-1PEJ6PRJFXOE | Gerardo | Medina González | M | México | Puebla | Basic | Active | 48 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-A1E4FZL8YKPU | 9327 | Tarjeta Débito | Active | USD | 359.52 |  | 2027-06-15 |  |
| PRD-LNC9LIRKRD3P | 2106 | Tarjeta Crédito | Active | USD | 807.35 | 21125.48 | 2026-02-20 | 0 |
| PRD-QS9LA6LFE711 | 7506 | Tarjeta Crédito | Active | USD | 670.84 | 38104.78 | 2028-08-17 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-1ASD0WXCOIHJPY31543Q | 2026-06-13 12:08:47 | 9327 | Withdrawal |  | 214.12 | USD | México | POS | Declined | 54 | 7.68 |
| TRX-WVD292XOGII35466G6S5 | 2026-05-29 20:57:31 | 9327 | Purchase | Super Ahorro | 26.35 | USD | México | ATM | Approved | 00 | 18.52 |
| TRX-25ESHBMZXW7Z8E2GDW2I | 2026-05-29 10:42:11 | 7506 | Purchase | Cable TV | 311.62 | USD | Spain | Web | Approved | 00 | 4.12 |

Cases, last 120 days:

_none_

### K08: CLI-116EIR62CLV8

Evidence: TRX-2YH4YRZV5LXOBUT92GND. All classes: K08, K12, K15.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-116EIR62CLV8 | Pilar | Reyes Morales | O | México | Monterrey | Basic | Active | 49 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-96I0120RJ68S | 3039 | Tarjeta Crédito | Active | USD | 1782.67 | 11014.52 | 2029-10-19 | 90 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-RQ7PYKEKV4V25U7VOH05 | 2026-06-17 21:27:23 | 3039 | Purchase | Tienda General | 197.49 | USD | México | POS | Approved | 00 | 13.71 |
| TRX-BI9W8H7PRZDV249YCSRU | 2026-06-12 21:55:33 | 3039 | Purchase | Internet Plus | 47.19 | USD | México | Web | Approved | 00 | 27.32 |
| TRX-2YH4YRZV5LXOBUT92GND | 2026-06-03 12:15:58 | 3039 | Purchase | Gasolinera Express | 246.96 | USD | México | POS | Approved |  | 11.98 |

Cases, last 120 days:

_none_

### K09: CLI-32Y366Z6DCJ3

Evidence: TRX-4O0OUOHSNXZ7W98T8OTV. All classes: K01, K05, K09, K13.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-32Y366Z6DCJ3 | Raquel Fernanda | Pérez Moreno | O | Argentina | Rosario | Basic | Inactive | 71 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-940986SMO6F7 | 8776 | Tarjeta Crédito | Active | ARS | 1033020.13 | 9507810.71 | 2028-05-29 | 0 |
| PRD-WRUAEQG4OD63 | 2651 | Tarjeta Débito | Active | ARS | 224494.80 |  | 2029-12-08 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-4O0OUOHSNXZ7W98T8OTV | 2026-06-12 00:35:19 | 2651 | Withdrawal |  | 90652.83 | ARS | Mexico | ATM | Approved | 00 | 24.55 |
| TRX-4XY66GLRSPCD497N4S2K | 2026-05-20 18:21:32 | 8776 | Withdrawal |  | 71524.46 | ARS | Argentina | ATM | Approved | 00 | 15.36 |

Cases, last 120 days:

_none_

### K10: CLI-2QSMH1WC6VAP

Evidence: TRX-8DQ55HI2VNDHEFHUH6OS, TRX-JNNB1I22HL8QU5RXTPEY. All classes: K02, K10, K11.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-2QSMH1WC6VAP | Héctor Arturo | Ríos Rodríguez | M | Colombia | Bogotá | Basic | Active | 57 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-2DEL3ZUNYVF8 | 0214 | Tarjeta Débito | Active | COP | 1989663.94 |  | 2024-11-06 |  |
| PRD-P9Y8AF8PMK1F | 9778 | Tarjeta Crédito | Active | COP | 10112891.48 | 52045967.63 | 2028-02-15 | 0 |
| PRD-YYJNM3HOIO01 | 2888 | Tarjeta Crédito | Active | COP | 12107513.43 | 161743476.58 | 2026-06-29 | 60 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-PRJ4XEG7EJ7NB3YGAH5B | 2026-06-17 18:59:04 | 0214 | Withdrawal |  | 1859646.27 | COP | Colombia | POS | Approved | 00 |  |
| TRX-6Y9GS672UK8YZCBB7IL3 | 2026-06-05 12:37:59 | 2888 | Purchase | Tienda General | 1051038.75 | COP | Colombia | ATM | Pending |  | 23.62 |
| TRX-JNNB1I22HL8QU5RXTPEY | 2026-06-05 10:21:04 | 2888 | Purchase | Ferretería | 167194.87 | COP | Colombia | POS | Approved | 00 | 2.97 |
| TRX-8DQ55HI2VNDHEFHUH6OS | 2026-05-30 20:10:13 | 9778 | Purchase | Conciertos Live | 210207.48 | COP | Colombia | App | Approved | 00 | 17.47 |

Cases, last 120 days:

_none_

### K11: CLI-4RESGE31U95O

Evidence: TRX-F9GJCEVMBO305NFNHQ9T. All classes: K10, K11, K12.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-4RESGE31U95O | Miguel | López Ospina | O | Colombia | Bogotá | Plus | Active | 34 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-IE77BU9D0VE5 | 8438 | Tarjeta Débito | Active | COP | 1444469.60 |  | 2028-03-13 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-VY7AAKC613UP96APOS6M | 2026-05-29 10:30:00 | 8438 | Purchase | Servicios Públicos | 1163763.75 | COP | Colombia | ATM | Approved | 00 |  |
| TRX-A6UUZ2IQA5DF7X5H7K6T | 2026-05-28 15:21:20 | 8438 | Purchase | Gasolinera Express | 577773.18 | COP | Colombia | POS | Approved | 00 | 8.05 |
| TRX-F9GJCEVMBO305NFNHQ9T | 2026-05-26 09:35:15 | 8438 | Purchase | Laboratorio Central | 1888340.47 | COP | Colombia | App | Approved | 00 |  |
| TRX-W6ZS2UH7AMOPWCRYNA76 | 2026-05-26 09:28:21 | 8438 | Purchase | Cable TV | 538780.50 | COP | Colombia | Web | Approved | 00 | 23.86 |

Cases, last 120 days:

_none_

### K12: CLI-16VESRAA8DYC

Evidence: CMP-LUDSZOK6FJYBV45CYG98, CMP-SJY3YVATACUS0BPGFGF3. All classes: K05, K12, K13, K15.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-16VESRAA8DYC | Pedro | Vega García | O | Argentina | Rosario | Basic | Active | 63 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-0J15VLKA6GJ1 | 0887 | Tarjeta Débito | Active | ARS | 308427.65 |  | 2029-05-12 |  |
| PRD-R3JW3LZSSO1H | 8071 | Tarjeta Crédito | Active | ARS | 185969.46 | 17497732.46 | 2028-03-29 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-NQLI330E9INQO6PT0IQF | 2026-06-09 02:39:17 | 8071 | Payment |  | 693499.90 | ARS | Argentina | ATM | Approved | 00 | 9.89 |
| TRX-7OC8CBN110LM3VH93ZV8 | 2026-05-28 12:38:48 | 0887 | Purchase | Centro Comercial | 147717.70 | ARS | Argentina | ATM | Approved | 00 |  |
| TRX-UTLDVJGDO7CNLM84VZ2A | 2026-05-22 10:05:26 | 0887 | Purchase | Uber | 2888.32 | ARS | Argentina | Web | Approved | 00 | 2.90 |

Cases, last 120 days:

_none_

### K13: CLI-3M640ZWWWMO6

Evidence: CMP-3X056PO0PS7WF358TLU0. All classes: K07, K13.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-3M640ZWWWMO6 | Fernanda | Luna Ruiz | O | México | Puebla | Basic | Active | 25 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-MCFVJO6SXTVU | 9826 | Tarjeta Crédito | Active | USD | 2202.96 | 45498.53 | 2029-11-22 | 0 |
| PRD-S9H8PQN9JKCD | 6440 | Tarjeta Crédito | Closed | USD | 1417.38 | 28461.74 | 2028-08-24 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-K8THY4BCQSE5A1TA5FN6 | 2026-06-16 04:59:44 | 9826 | Purchase | Tienda General | 428.75 | USD | México | Transfer | Approved | 00 | 16.61 |
| TRX-9396CRKGL81HH04I7Q0Q | 2026-06-14 03:45:23 | 9826 | Purchase | Cable TV | 10.82 | USD | México | ATM | Declined | 54 | 4.38 |
| TRX-TGQ08D98GT3V9TEPUCLA | 2026-06-13 08:32:39 | 9826 | Purchase | Teatro Nacional | 63.10 | USD | USA | POS | Approved | 00 | 6.19 |

Cases, last 120 days:

_none_

### K14: CLI-42YV0ESQLZ4M

Evidence: CMP-1NJ0763V27GAZ7MHS91A, CMP-V390A2G032RTLKQ18XDX. All classes: K01, K03, K12, K14, K15.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-42YV0ESQLZ4M | Rafael Lorena | Ramírez Flores | O | México | Querétaro | Basic | Inactive | 45 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-8LJBC2LNHLCM | 9035 | Tarjeta Crédito | Active | USD | 1324.24 |  | 2029-03-28 | 0 |
| PRD-G1PGTZ4FEDCT | 1780 | Tarjeta Crédito | Active | USD | 1979.33 | 36970.55 | 2031-02-26 | 0 |
| PRD-YVC20GECS3AE | 4617 | Tarjeta Crédito | Active | USD | 1066.85 | 5254.37 | 2027-10-25 | 0 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-LBRX6MJVQ53D78OV5KWP | 2026-06-17 17:26:38 | 4617 | Purchase | Ferretería | 151.73 | USD | México | POS | Approved | 00 | 11.58 |
| TRX-XDWVJ408V3875LRSJZEM | 2026-06-10 07:47:32 | 1780 | Purchase | Ferretería | 202.68 | USD | México | Web | Approved | 00 |  |
| TRX-0NC1QO0J3MKZ12W7HP8G | 2026-05-23 00:20:23 | 4617 | Withdrawal |  | 183.91 | USD | México | Web | Approved | 00 |  |

Cases, last 120 days:

_none_

### K15: CLI-2HBNYGCDHCAW

Evidence: CLI-2HBNYGCDHCAW. All classes: K03, K06, K12, K15.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-2HBNYGCDHCAW | Andrés | Medina Aguilar | O | México | Monterrey | Premium | Active | 77 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-R6L6C49X3VM0 | 1346 | Tarjeta Crédito | Active | USD | 1905.99 | 44631.78 | 2027-05-11 | 0 |
| PRD-R83Z2TCVG9OT | 0507 | Tarjeta Débito | Active | USD | 598.23 |  | 2029-02-12 |  |
| PRD-V0VUJD2677SB | 0832 | Tarjeta Crédito | Active | USD | 1976.64 | 39034.03 |  | 0 |
| PRD-WR04WTQTTXI1 | 5577 | Tarjeta Débito | Active | USD | 940.56 |  | 2028-10-27 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-FVD7GXM24UWACDCZY7MQ | 2026-06-07 01:45:16 | 1346 | Purchase | Mercado Central | 421.07 | USD | México | POS | Approved | 00 | 1.61 |
| TRX-YAJ507WYI2I6J3ZJOI9D | 2026-06-03 19:17:08 | 5577 | Withdrawal |  | 398.82 | USD | México | ATM | Reversed | 14 |  |
| TRX-YYU0TW7AT2D9CMGY5JJH | 2026-05-24 10:21:26 | 0507 | Purchase | Restaurante El Buen Sabor | 412.52 | USD | México | POS | Approved | 00 |  |

Cases, last 120 days:

_none_

### K16: CLI-47BQDE276OXT

Evidence: CLI-47BQDE276OXT. All classes: K07, K12, K16.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-47BQDE276OXT | Ana | Restrepo Ruiz | F | Colombia | Cali | Basic | Active | 24 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-MXDXQ7PK2JWZ | 7875 | Tarjeta Crédito | Active | COP | 3066062.63 | 121110194.44 | 2027-04-11 | 180 |
| PRD-NBQU8EO2ZH3I | 8980 | Tarjeta Débito | Active | COP | 5467794.25 |  | 2031-05-26 |  |
| PRD-Y1AM0LMN8TO2 | 2647 | Tarjeta Crédito | Active | COP | 5554727.92 | 181017613.49 | 2028-06-26 | 90 |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-7XGAZSXNYT6BBZOU1FYW | 2026-06-17 13:51:37 | 7875 | Purchase | Óptica Visión | 1411479.43 | COP | Colombia | POS | Declined | 54 | 4.20 |
| TRX-5IMZZL209UTWKNWS9T8J | 2026-06-01 18:25:06 | 8980 | Payment |  | 2419628.11 | COP | Colombia | POS | Approved | 00 | 6.39 |

Cases, last 120 days:

_none_

### K17: CLI-56ZGCLR0HZIR

Evidence: CLI-56ZGCLR0HZIR. All classes: K05, K17.

| customer_id | first_name | last_name | gender | country | city | segment | customer_status | age |
|---|---|---|---|---|---|---|---|---|
| CLI-56ZGCLR0HZIR | Alejandra | Moreno Ramírez | F | Colombia | Medellín | Basic | Active | 37 |

Cards:

| product_id | last4 | product_type | product_status | currency | current_balance | credit_limit | expiration_date | days_past_due |
|---|---|---|---|---|---|---|---|---|
| PRD-80RWRYK2ULH3 | 8846 | Tarjeta Crédito | Active | COP | 7340918.42 | 49955848.45 | 2028-04-23 | 0 |
| PRD-8S9WC5HG3HLV | 0895 | Tarjeta Crédito | Active | USD | 1159.81 | 20707.72 | 2026-12-09 | 0 |
| PRD-EM9P3ERFOJH7 | 4192 | Tarjeta Débito | Closed | COP | 4080859.24 |  | 2028-02-11 |  |

Card transactions, last 30 days:

| transaction_id | transaction_date | last4 | transaction_type | merchant_name | amount | currency | transaction_country | channel | transaction_status | response_code | fraud_score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-6PLBFCOJ5NODVT4DHZ8N | 2026-06-08 09:10:56 | 8846 | Purchase | Tienda General | 1234780.40 | COP | Colombia | ATM | Approved | 00 |  |
| TRX-GCPCZZMVJM8FHNB3PCX8 | 2026-06-02 16:05:43 | 0895 | Withdrawal |  | 325.50 | USD | Colombia | App | Approved | 00 | 20.77 |
| TRX-2EZWAER1ZG6MJPXORABS | 2026-05-29 08:41:05 | 8846 | Purchase | Ferretería | 1155772.78 | COP | Colombia | ATM | Approved | 00 |  |

Cases, last 120 days:

_none_

## 7. Known limits

- **Synthetic rules are labelled.** C8–C12 invent values by rule; the run record and this document say so.
- **Some defects can't be fixed.** Uniform amounts and hours (D22) would need synthesis, and segment vs age (D38) is left alone.
- **The score is a draft.** It ranks within a cell; its weights aren't tuned.
- **C11 is approximate.** Its deadlines are calendar-day equivalents of business days (×7/5), not exact country calendars.
- **Rare scenarios stay rare among real customers.** There are 3 fraud flags and 7 open unrecognized-charge cases in the 1,500. The evaluation harness injects them into `EVL-` clones, with labels derived from records plus policy.
