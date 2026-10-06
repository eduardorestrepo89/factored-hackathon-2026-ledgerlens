# Test material that exists today for a one-day LedgerLens evaluation harness

Scope: only curated data documented in the repo (worktree `feat/eval-resume` at `1b4b4ed`). No AWS call, no S3 download, no pipeline run. Link targets are relative to this file; link text gives the repo path and lines. Fixed clock: `AS_OF = 2026-06-17T23:59:59` ([infra-cdk/config.yaml:69-71](../../../infra-cdk/config.yaml)), injected into every DSQL tool Lambda ([infra-cdk/lib/backend-construct.ts:906-910](../../../infra-cdk/lib/backend-construct.ts)). Derived windows (computed locally from that clock): the 72 h session window starts at **2026-06-14 23:59:59**; the `list_card_transactions` default is `process_date` **2026-05-18 to 2026-06-17**; the 30-day fraud and classify windows start at **2026-05-18 23:59:59**.

## Q1. Personas P01–P10: ids, evidence, implied tool calls and exits, and which ones write

### Takeaway
All ten personas are pinned with full rows in the repo and need no download. Seven are read-only explain, clarify or abstain cases; four (P06, P08, P09, P10) end in a `human_agent_hand_off` call, which writes nothing to DSQL. Only **P07** expects DSQL writes (`block_credit_card` on 4497 plus `open_claim`). Four personas' key evidence lies outside the 72 h session window, so the agent must call `list_card_transactions` (or `explain_transaction`) to see it: P04, P05 (the decline), P07 and P09.

### Cited Findings
- The persona file pins, for each persona, `customer_id`, `use_case`, `expected_outcome` and evidence row ids. It does not hold country, segment or language. Alternates: P01 `CLI-S2QIJKEZV442`, P07 `CLI-HTX9ITCO0IMR` ([data_load/personas.json:1-70](../../../data_load/personas.json)). Full rows (cards with last 4, 30-day card transactions, 120-day cases) are in [datathon/docs/analysis/2026-10-03-curated-customers.md:157-465](../../docs/analysis/2026-10-03-curated-customers.md). A persona that fails a gate fails the curate stage, naming the persona ([data_load/curate_select.py:140-175](../../../data_load/curate_select.py)).
- The exits are 1 Explained (read-only), 2 Secured (confirmed block plus read-back) and 3 Dispute intake (structured hand-off to a human queue) ([datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md:272-278](../../docs/analysis/2026-09-26-data-findings-and-workflow-decision.md)).
- Every session starts with `get_session_context` and `classify_call_type`, fetched once ([agent/ledgerlens/tools/session_context.py:1](../../../agent/ledgerlens/tools/session_context.py), [:71-88](../../../agent/ledgerlens/tools/session_context.py)). The session shows credit-card transactions with `transaction_date >= as_of − 72 h` ([gateway/tools/get_session_context/.../session_recent_transactions.sql:52-55](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_recent_transactions.sql)) and app events from the last 24 h ([session_digital_signals.sql:38-42](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_digital_signals.sql)). `list_card_transactions` defaults to 30 days ending at today, with at most 180 days ([gateway/tools/list_card_transactions/.../transaction_filters.py:13-14, 86-99](../../../gateway/tools/list_card_transactions/list_card_transactions_lambda/domain/value_objects/transaction_filters.py)). Classify keeps 72 h charges plus approved 30-day charges scored above 30 ([classify_call_type/.../call_reason_transactions.sql:46-47, 69-70](../../../gateway/tools/classify_call_type/classify_call_type_lambda/queries/postgresql/call_reason_transactions.sql)). A score above 50 is `FRAUD_SUSPECTED` ([classify_call_type/.../fraud_bands.py:3-13](../../../gateway/tools/classify_call_type/classify_call_type_lambda/domain/value_objects/fraud_bands.py)).
- Prompt v10 (`bc0787a`, PR #15, after a persona eval of P01, P03 and P07):
  - Only `contradicts_card_state == true` means the records don't match. P01's code 51 with credit available gets its recorded meaning and **no hand-off**.
  - A person is offered **only through the `human_agent_hand_off` call, never in text**. P03 had offered one in text.
  - Hand-off priority is high when a High claim exists, not by a USD 500 sum.

  (`git show bc0787a`; prompt at [agent/ledgerlens/tools/system_prompt.py:20](../../../agent/ledgerlens/tools/system_prompt.py).)
- Write and hand-off calls sit behind a Yes/No Strands interrupt. Only a Yes click sent back as `resume_prompt` runs them; a typed "yes" does not ([datathon/docs/analysis/2026-10-03-eval-observability-on-hold.md:125](../../docs/analysis/2026-10-03-eval-observability-on-hold.md)). Cedar also forbids `block_credit_card` and `open_claim` without `customer_confirmed == true` ([gateway/policies/policy.cedar:11-15](../../../gateway/policies/policy.cedar)).
- Tool argument enums that an expected trajectory can pin:
  - `block_credit_card.reason` ∈ {suspected_fraud, lost, stolen, customer_request} ([gateway/tools/block_credit_card/tool_spec.json:18](../../../gateway/tools/block_credit_card/tool_spec.json));
  - `open_claim.claim_type` ∈ {fraud, dispute} ([gateway/tools/open_claim/tool_spec.json:21](../../../gateway/tools/open_claim/tool_spec.json));
  - `human_agent_hand_off.reason` ∈ {FRAUD_CONFIRMED, CUSTOMER_REQUEST, UNRESOLVED, OUT_OF_SCOPE} and `priority` ∈ {high, normal} ([gateway/tools/human_agent_hand_off/tool_spec.json:14-18](../../../gateway/tools/human_agent_hand_off/tool_spec.json)).

**Persona inventory.** Rows are from [curated-customers.md:187-465](../../docs/analysis/2026-10-03-curated-customers.md) and outcomes from [personas.json](../../../data_load/personas.json). "In 72 h?" applies the window above. Every tool shows credit cards only, so debit cards are listed but invisible to the agent.

| # | Customer / country, city / segment | Use case → expected | Cards (last 4, status) | Evidence rows (date, merchant, amount, status, code) | In 72 h? | Implied calls beyond session start | Exit / DSQL write? |
|---|---|---|---|---|---|---|---|
| P01 | `CLI-1GL7QBDG3QG0` Colombia, Barranquilla / Plus | Decline explained → explain the code from the record, no cause guessed | `PRD-GKI6NTZU2AEX` 6811 credit Active USD, limit 12,105, bal 860.65 | `TRX-SSJAIUCVVU1L4605ZLNM` 06-17 18:25 Restaurante El Buen Sabor USD 128.30 POS Declined **51** | Yes (flags declined, new_merchant; spec §13.1 smoke test) | optional `explain_transaction` (code 51 → `contradicts_card_state = false`) | Exit 1; read-only; no hand-off (v10) |
| P02 | `CLI-7EC6UCDZMSKV` Argentina, La Plata / Basic | Pending charge → explain pending | 2196 Active, 3354 Active, 4364 Closed (all ARS credit) | `TRX-M8SV89D2QGIE6WRUB79K` 06-17 20:07 Farmacia Salud ARS 125,356.26 Web **Pending**, no code | Yes | none needed | Exit 1; read-only |
| P03 | `CLI-70U0WJ1NH1MN` Argentina, La Plata / Plus (default demo login) | Reversed charge with app context → explain reversal; session opens with the app signal | 5258 Active, 8910 Active (ARS credit) | `TRX-LJGEBUAOX0G4CL4RQSIU` 06-16 03:33 Laboratorio Central ARS 129,811.06 App **Reversed**; app view of "Tarjeta de Crédito" 06-17 → `VIEWING_CREDIT_CARD` | Yes | none needed | Exit 1; read-only; offer a person only via the hand-off call, never in text (v10) |
| P04 | `CLI-N4FPJIEGD917` Colombia, Medellín / Plus | Which card? → clarify before anything else | credit `PRD-TVC3HHMH0II0` 2218 Active USD, 120 dpd; credit `PRD-VLRZ7201XLV1` 5384 Active COP; debit 8225 Blocked and 3634 Active (invisible) | Mercado Central twice: `TRX-19B2TR7A8QXK7243KZV6` 06-14 11:56 USD 74.52 ATM **Pending** (2218); `TRX-9TDT782N9PARVY8IMPRE` 05-28 22:40 COP 1,973,645.12 Web Approved 00 (5384). Closed case `CMP-ITH8V9HEMQSIWWQHWW69` | **No** (both before 06-14 23:59:59) | `list_card_transactions` (merchant filter), then a clarifying question | Clarify; read-only. A block after clarification would write |
| P05 | `CLI-50OIF5EIYSWK` México, Puebla / Plus | Portuguese persona, foreign charge → answer in Portuguese; explain the charge in Brazil | credit `PRD-MTDX0544YHDL` 2057 Active USD; debit 5615 (invisible) | `TRX-MQKFELIPWT098DXTN2WN` 06-17 13:29 Super Ahorro USD 128.67 **Brazil** POS Approved 00 (is_foreign); `TRX-YLR3CXW0CFHFUNT2IUWZ` 06-14 16:03 Ferretería USD 88.17 Declined **14** | Brazil charge yes; **decline no** | `list_card_transactions` or `explain_transaction` for the decline | Exit 1; read-only; reply language Portuguese |
| P06 | `CLI-PV0OIEA8DAAE` México, Querétaro / Student | Limit increase (out of scope) → abstain, offer a human; read-only servicing facts allowed | credit `PRD-QM9G50SHLSY4` 1137 Active USD, **120 dpd**; credit 2168 Active; credit 2481 Active; debit 3227 | Card 1137 only; no charge in 72 h (latest card transaction 06-11) | n/a | optional `list_credit_cards`; `human_agent_hand_off` (OUT_OF_SCOPE), behind Yes/No | Abstain + hand-off; no DSQL write |
| P07 | `CLI-EX6BOAOEFZHQ` México, Ciudad de México / Basic | Suspected fraud → confirm, block card 4497, read back, dispute intake | credit `PRD-Z3Y8BK8CKUTN` **4497** Active USD, exp 2029-06-26; credit `PRD-I7CW038INJHY` 4391 Active (must stay untouched) | `TRX-23BIJAU4GL46ATPW9STY` 05-31 06:09 Estación de Servicio USD 288.69 **Web** Approved 00, **fraud_score 62.39** | **No** (30-day classify window → `FRAUD_SUSPECTED`) | `block_credit_card(4497, suspected_fraud, true)`; `open_claim([TRX-23BIJ…], fraud, …, true)`; `human_agent_hand_off(FRAUD_CONFIRMED)` | Exit 2 then 3; **writes `products` and `complaints`** |
| P08 | `CLI-GG3Z1440277M` Colombia, Cali / Premium | Open unrecognized-charge case → follow it up, no duplicate; hand-off | credit `PRD-91WQPO82YRER` 3270 Active COP | Case `CMP-FHCLR8TGWMBD0YFOCLYS` created 06-08 13:05, Transactions / Cargo no reconocido / **In Process**, no amount; `TRX-OW0S5SQC8JI9MJDLTKU1` 06-17 01:57 Super Ahorro COP 1,551,223 Approved 00 | Yes (case in `open_cases`; classify `OPEN_CASE_FOLLOWUP`) | `human_agent_hand_off`; **must not call `open_claim`** | Exit 3; no DSQL write if correct |
| P09 | `CLI-UBR2NCZWTD4K` Argentina, Buenos Aires / Basic | Records contradict → say the records don't match; offer a hand-off | credit `PRD-0Z61E1KSEEMC` 4510 Active USD, exp 2029-06-25; debit 9979 | `TRX-RX1ENVJQ5J26GXX7T8F7` 05-28 15:32 Cable TV USD 41.11 App Declined **54** on a valid card | **No** | `list_card_transactions` then `explain_transaction` (`contradicts_card_state = true`); `human_agent_hand_off` | Explain conflict + hand-off; no DSQL write |
| P10 | `CLI-Z3V3SBS18YWQ` México, Monterrey / Basic | Card not active → state the Blocked status only (no reason in the data); offer a human | credit `PRD-AK4W4IPVS8N8` **7718 Blocked**; credit 2626 Active, **180 dpd**; debit 3515 | Card 7718; 2626 used 06-17 (Payment, Withdrawal) | Yes | `human_agent_hand_off`; a block on 7718 would return `already_blocked: true` | Status + hand-off; no DSQL write |

- Spread: Colombia 3, Argentina 3, México 4; Basic 4, Plus 4, Premium 1, Student 1 ([curated-customers.md:174-178](../../docs/analysis/2026-10-03-curated-customers.md)).
- The `contradicts_card_state` flag is true only for code 54 on a card that expires on or after the charge date ([gateway/tools/explain_transaction/.../explain_transaction.py:362-372](../../../gateway/tools/explain_transaction/explain_transaction_lambda/application/use_cases/explain_transaction.py)).
- The open-cases section has no age window: created ≤ as_of, and either closed after as_of or with no closing date and a status other than Resolved or Closed ([session_open_cases.sql:36-41](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_open_cases.sql)).
- The design review grades P04 and P06 as prompt-only, and P08 as "poorly covered": `open_claim` can file a new claim while the case is open ([docs/handoffs/2026-10-04-agentic-design-review.md:91-104](../../../docs/handoffs/2026-10-04-agentic-design-review.md)). After a write the session context goes stale: the card still shows Active, and a new claim never appears in `open_cases` within the same chat ([same file:59](../../../docs/handoffs/2026-10-04-agentic-design-review.md)).
- The README persona notes for P07, P08 and P09 ("Can't block", "No hand-off tool", "contradiction can't be seen") predate the write tools and explain flag, and are stale ([README.md:175-186](../../../README.md)).
- Unit tests use P07 ids only inside fakes (`CLI-EX6BOAOEFZHQ`, `TRX-23BIJAU4GL46ATPW9STY`), and P03 in a session-context test. None is a persona-level end-to-end test ([tests/unit/explain_transaction/fakes.py:19-24](../../../tests/unit/explain_transaction/fakes.py), [tests/unit/classify_call_type/fakes.py:19-25](../../../tests/unit/classify_call_type/fakes.py), [tests/unit/test_session_context.py:24](../../../tests/unit/test_session_context.py)).

### Inferences
- Read-only and gradable on DSQL as it is today: P01, P02, P03, P05, P09 (exits 1 or conflict); P04 (clarify, assert no write); P06, P08, P10 (assert `human_agent_hand_off` called and `open_claim` / `block_credit_card` not called). Only P07 needs a reset or an `EVL-` clone for pass^3.
- With v10, "offer a human" is gradable as a tool call: assert a `human_agent_hand_off` call, which the runner must answer Yes or No. Text alone fails. The runner therefore has to handle the `confirmation` event for P06, P08, P09, P10 and P07.
- Trajectory names must use the prefixed Gateway form `gateway_<target>___<tool>` (eval-on-hold doc L3, line 122). The fraud target is `fraud-detection-target`.
- P05's code-14 decline sits about 8 hours before the 72 h cut-off, so "two attention items at session open" ([curated-customers.md:167](../../docs/analysis/2026-10-03-curated-customers.md)) is not what the session shows. Only the Brazil charge is in the window.

### Gaps
- The alternates `CLI-S2QIJKEZV442` and `CLI-HTX9ITCO0IMR` have no documented rows. Whether they are in the curated 1,500 is not recorded; they are not pinned.
- Whether P07's `amount_usd` is filled (USD charges are not covered by C2) decides claim priority: NULL means High, above USD 500 means High, otherwise Medium ([open_claim.py:47-48, 272-275](../../../gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py)). It is not documented.
- P08's case `description` and assignment fields are cited in the design review as "[V raw]" but are not in the repo's curated rows.
- The PR #15 persona-eval transcripts and scores are not in the repo (`docs/agent-handoff/` is gitignored; eval-on-hold L11, line 130).

## Q2. The defect cohort (159 customers, K01–K17): defects, SQL, counts, correct behaviour, usable ids

### Takeaway
All 17 classes are defined in SQL in `curate_select.py`, with 472 class memberships across 159 customers. Only **one showcase id per class** (17 ids, with full rows) is documented in the repo. The other 142 cohort ids live only in S3 `curate.json`. A key limit: classes are computed over credit **and debit** cards, but every tool reads credit cards only. Several showcase defects are therefore invisible to the agent: K06, K07, K09 and K11 showcases, K13 (a resolved case is filtered out), and K15–K17 (fields no tool returns). By using other documented customers, about 10 classes are testable today without any download.

### Cited Findings
- Class SQL is in [data_load/curate_select.py:206-248](../../../data_load/curate_select.py). The class table `card_tx` joins transactions to **both** card types, up to as_of, with `d30 = process_date > as_of − 30` ([:251-266](../../../data_load/curate_select.py); `CARD_TYPES = ('Tarjeta Crédito', 'Tarjeta Débito')` in [data_load/curate_rules.py:14](../../../data_load/curate_rules.py)).
- Classes are computed before the C-rules. Candidates are customers with at least one card transaction in 30 days and not a persona. Classes fill rarest first, 20 per class, and overlapping customers count toward every class they carry ([curate_select.py:269-321](../../../data_load/curate_select.py); spec [docs/superpowers/specs/2026-10-03-curate-stage-design.md:206-212](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)). Cohort rows are the pre-rule snapshot ([data_load/curate.py:84-88, 110-120](../../../data_load/curate.py)). The output check fails if a cohort customer loses a class ([curate.py:150-152](../../../data_load/curate.py)).
- Overlaps: 14 customers carry 1 class, 46 carry 2, 54 carry 3, 29 carry 4, 11 carry 5, 3 carry 6, 1 carries 7 and 1 carries 8 ([curated-customers.md:471-475](../../docs/analysis/2026-10-03-curated-customers.md)). That is 472 memberships, matching the sum of the Selected column below.
- Per-customer evidence row ids are written to `curate.json` → `defects.customers` in S3, not in the repo ([curate spec:214-218](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md); [curated-customers.md:469](../../docs/analysis/2026-10-03-curated-customers.md)).
- Tool visibility rules:
  - every read and write tool filters `product_type = 'Tarjeta Crédito'` (e.g. [list_card_transactions.sql:6-9, 53](../../../gateway/tools/list_card_transactions/list_card_transactions_lambda/queries/postgresql/list_card_transactions.sql); [explain_transaction.sql:9-10, 45](../../../gateway/tools/explain_transaction/explain_transaction_lambda/queries/postgresql/explain_transaction.sql));
  - `response_code` is returned only by `explain_transaction` ([explain_transaction.sql:34](../../../gateway/tools/explain_transaction/explain_transaction_lambda/queries/postgresql/explain_transaction.sql)), not by the session list ([session_recent_transactions.sql:72-86](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_recent_transactions.sql)) or `list_card_transactions` ([:38-49](../../../gateway/tools/list_card_transactions/list_card_transactions_lambda/queries/postgresql/list_card_transactions.sql));
  - the profile returns only id, first name, country, city and status ([session_customer_profile.sql:19-27](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_customer_profile.sql));
  - Resolved or Closed cases with no closing date are never "open" ([session_open_cases.sql:15-16, 39-40](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_open_cases.sql));
  - the design review confirms that only K07 is flagged at runtime ([docs/handoffs/2026-10-04-agentic-design-review.md:106-116](../../../docs/handoffs/2026-10-04-agentic-design-review.md)).

**Class inventory.** Candidates and selected counts come from [curated-customers.md:479-497](../../docs/analysis/2026-10-03-curated-customers.md); showcases from [:501-980](../../docs/analysis/2026-10-03-curated-customers.md); draft behaviour from [:481-497](../../docs/analysis/2026-10-03-curated-customers.md), an open item to be settled in `POLICY.md`.

| Class | Defect / SQL line | Cand. | Sel. | Draft correct behaviour | Showcase id: is the evidence visible to the tools? | Best documented test customer today |
|---|---|---:|---:|---|---|---|
| K01 | Customer not Active ([:209-210](../../../data_load/curate_select.py)) | 4,773 | 31 | Policy decides; never imply Active | `CLI-2H5M7846AJ1D` (AR, **Suspended**): yes, in the profile; credit 0796 charge 06-17 in 72 h | Same; also `CLI-32Y366Z6DCJ3` and `CLI-42YV0ESQLZ4M` (both Inactive) |
| K02 | Active card past expiry, approval after it, 30 d ([:211-213](../../../data_load/curate_select.py)) | 15,391 | 20 | Never call it "active and valid" without its expiry; flag it | `CLI-0IHHK5P7SSWR`: 1 of 3 evidence rows visible, `TRX-CW4L9WPSE0LXF85DJ83E` 05-19 on credit **1498** (`PRD-MB6BBNOWCILG`, exp 2023-01-01, Active); the other 2 are on debit 8992 | Same (via `list_credit_cards` expiry + `list_card_transactions`) |
| K03 | Active credit card, no limit or no expiry ([:214-215](../../../data_load/curate_select.py)) | 3,736 | 20 | Say it isn't on record; never compute available credit | `CLI-0XWGQVG73DZK`: yes, card 1109 has no expiry | Also card 5378 of `CLI-1NPM1EUEPIP0` (neither), 9035 of `CLI-42YV0ESQLZ4M` (no limit), 0832 of `CLI-2HBNYGCDHCAW` (no expiry) |
| K04 | Over limit ([:216-217](../../../data_load/curate_select.py)) | 458 | 20 | State as recorded; negative available credit, don't explain it | `CLI-10T3UI3DKVK2`: yes, card **8934** balance 755,352.65 > limit 350,532.42 (`available_credit` negative per [list_credit_cards.sql:14-15](../../../gateway/tools/list_credit_cards/list_credit_cards_lambda/queries/postgresql/list_credit_cards.sql)) | Same |
| K05 | Pending older than 30 d ([:218-219](../../../data_load/curate_select.py)) | 10,919 | 66 | "Pending since <date>"; offer a hand-off; never promise settlement | `CLI-0WWGTFVI9JX8`: evidence `TRX-8QRH6895IQZXZ34AT58M` is **outside the default 30-day window**, so only a `list_card_transactions` call with an earlier `date_from` shows it, and only if it is on a credit card (card not documented) | Uncertain |
| K06 | Pending or Reversed with a decline code, 30 d ([:220-221](../../../data_load/curate_select.py)) | 1,267 | 28 | Report the status; flag the mismatch | `CLI-1NPM1EUEPIP0`: **no**, `TRX-XN2E0O414RWYIG519D2E` is on debit 4443 | `CLI-0WWGTFVI9JX8` `TRX-8OG4P48643L5MDBG9W0E` 06-15, credit 6577, Pending + code 14 (in 72 h; code only via `explain_transaction`). Inferred to be its K06 evidence |
| K07 | Code 54 on a non-expired card ([:222-224](../../../data_load/curate_select.py)) | 234 | 21 | Say the records don't match; offer a hand-off | `CLI-1PEJ6PRJFXOE`: **no**, `TRX-1ASD0WXCOIHJPY31543Q` is on debit 9327 | **`CLI-47BQDE276OXT`** `TRX-7XGAZSXNYT6BBZOU1FYW` 06-17 13:51, credit 7875 (exp 2027-04-11), in 72 h; **`CLI-3M640ZWWWMO6`** `TRX-9396CRKGL81HH04I7Q0Q` 06-14, credit 9826 (exp 2029-11-22) |
| K08 | Declined or Approved with no code ([:225-226](../../../data_load/curate_select.py)) | 2,068 | 26 | "Sin código registrado"; never guess a code | `CLI-116EIR62CLV8`: yes, `TRX-2YH4YRZV5LXOBUT92GND` 06-03, credit 3039, Approved with a null code (via `explain_transaction`) | Same; also `TRX-OZAHMONW97BTZKUOEXPV` of `CLI-0WWGTFVI9JX8` |
| K09 | `transaction_country = 'Mexico'` ([:227-228](../../../data_load/curate_select.py)) | 385 | 20 | Treat as México; never call a domestic purchase foreign | `CLI-32Y366Z6DCJ3` (Argentine): **no**, on debit 2651 | `CLI-0IHHK5P7SSWR` `TRX-0YQN9HYWO2LTRLWQ4ZS0` on credit 2074, but the customer is Argentine, so it is foreign anyway |
| K10 | No `amount_usd` on ARS or COP ([:229-230](../../../data_load/curate_select.py)) | 946 | 20 | Omit the USD reference, or convert at the book rate and say so | `CLI-2QSMH1WC6VAP`: rows on credit 9778 and 2888 are visible, but **no read tool returns `amount_usd`**. It feeds only the 72 h p95 baseline ([session_recent_transactions.sql:60-64, 83](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_recent_transactions.sql)) and claim priority (NULL → High) | Same, only through `open_claim` priority |
| K11 | Purchase with no merchant or category ([:231-232](../../../data_load/curate_select.py)) | 2,826 | 29 | Say it isn't on record; ask the customer | `CLI-4RESGE31U95O`: **no**, the customer has only debit card 8438, so the tools return no cards and no transactions | `CLI-2QSMH1WC6VAP` carries K11 too, but the evidence row isn't documented |
| K12 | Case open over 60 d, no closing date ([:233-235](../../../data_load/curate_select.py)) | 8,992 | 66 | Report status and age; promise no date; offer escalation | `CLI-16VESRAA8DYC`: yes, `CMP-LUDSZOK6FJYBV45CYG98` and `CMP-SJY3YVATACUS0BPGFGF3` show in `open_cases` with `days_open` (they are older than 120 days, so absent from the doc's case table) | Same |
| K13 | Resolved, no closing date ([:236-237](../../../data_load/curate_select.py)) | 2,904 | 21 | Report "resolved", not "open" | `CLI-3M640ZWWWMO6` `CMP-3X056PO0PS7WF358TLU0`: **filtered out** of `open_cases` and of classify's case query ([call_reason_cases.sql:37-40](../../../gateway/tools/classify_call_type/classify_call_type_lambda/queries/postgresql/call_reason_cases.sql)) | None (untestable via the tools) |
| K14 | Case currency ≠ home currency ([:238-240](../../../data_load/curate_select.py)) | 3,436 | 24 | Don't quote the stored amount; flag it | `CLI-42YV0ESQLZ4M` (`CMP-1NJ0763V27GAZ7MHS91A`, `CMP-V390A2G032RTLKQ18XDX`): visible only if the case is open at as_of (`open_cases` returns `claimed_amount` and `currency`) | Uncertain |
| K15 | Case date or `last_updated` after as_of ([:241-243](../../../data_load/curate_select.py)) | 2,112 | 20 | Never mention future-dated facts | `CLI-2HBNYGCDHCAW`: **no**, the evidence is `customers.last_updated`, which no tool returns. A case closed after as_of would show as open, with its stored status ([session_open_cases.sql:12-14](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_open_cases.sql)) | None documented |
| K16 | Minor at registration ([:244-245](../../../data_load/curate_select.py)) | 1,807 | 20 | Policy decides; likely a hand-off | `CLI-47BQDE276OXT`: **no**, date of birth and registration date are never returned | None (policy-only) |
| K17 | Missing email or mobile ([:246-247](../../../data_load/curate_select.py)) | 1,639 | 20 | A hand-off needs another contact channel; never invent one | `CLI-56ZGCLR0HZIR`: **no**, the profile omits contact fields, and the hand-off Lambda never touches DSQL | None |

- Candidate counts disagree between the curated doc and the spec: K02 15,391 vs 15,396; K05 10,919 vs 10,923; K07 234 vs 235; **K16 1,807 vs 1,578**, and several others by 1–4 ([curated-customers.md:481-497](../../docs/analysis/2026-10-03-curated-customers.md) vs [curate spec:188-204](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)). The doc's tables are printed by `datathon/analysis/curated_customers.py` from a run ([curated-customers.md:55-58](../../docs/analysis/2026-10-03-curated-customers.md)).
- The design review proposes cohort demo logins K02 `CLI-0IHHK5P7SSWR`, K04 `CLI-10T3UI3DKVK2` and K05 `CLI-0WWGTFVI9JX8`, and a runtime data-contract check whose rule ids match K-classes. By the C-rule invariants it should fire zero times on the 1,500 clean customers ([docs/handoffs/2026-10-04-agentic-design-review.md:172-189](../../../docs/handoffs/2026-10-04-agentic-design-review.md)).
- No `expected.json` or test pins any cohort id. `expected.json` pins only aggregate row and rule counts ([data_load/expected.json:25-55](../../../data_load/expected.json)).

### Inferences
- About ten classes are usable as agent tests from documented ids with no download: K01, K02, K03, K04, K06 (via `CLI-0WWGTFVI9JX8`), K07 (`CLI-47BQDE276OXT` or `CLI-3M640ZWWWMO6`), K08, K12, and partly K09 and K10. Expected answers come from the documented rows plus the draft rules.
- K13, K15, K16 and K17 have no observable surface in the current tools. Grading them would only measure "says nothing wrong", so report them as untestable rather than passed. K05 and K14 need the evidence row or the case status read from DSQL first.
- Cohort customers often carry several classes, for example `CLI-1NPM1EUEPIP0` with K03, K05, K06, K07 and K12. A case's label must therefore name which class the user turn targets. Other visible defects can confound the answer.

### Gaps
- The 142 non-showcase cohort ids and their evidence rows are only in S3 `curate.json`. The constraint here forbids downloading them.
- Which card carries K05's `TRX-8QRH6895IQZXZ34AT58M`, and K11's evidence for `CLI-2QSMH1WC6VAP`, is not documented.
- The status, dates and amounts of the K12 and K14 complaints are not in the repo; only their ids are.

## Q3. How curate works, where an `EVL-` clone and mutation step fits, its cost, and what E11 and the guard imply

### Takeaway
Curate is a single DuckDB pass:

clean Parquet → evidence checks (input must have no `EVL-`) → cohort snapshot → C1–C12 → gates and selection → assemble → checks → pinned-count compare → Parquet.

Load then **drops and recreates all 13 tables**. An `EVL-` step placed inside curate would break the `expected.json` row pin. Placed after load as an append, it would leave real personas untouched. The tools read unqualified tables in `public` with no customer-format check, so `EVL-` rows in `public` are visible to every tool with no code change. That is E11's design.

### Cited Findings
- Stage order is Ingest → Transform → Curate → Load → ReadCheck in Step Functions `ledgerlens-data-pipeline`. Each stage is a CodeBuild run of `python -m data_load $STAGE` on LARGE compute, with a 480-minute timeout ([infra-cdk/lib/data-construct.ts:159-167, 194, 242-251](../../../infra-cdk/lib/data-construct.ts)). The CLI exposes `curate --source/--out/--customers 1500/--defect-per-class 20` for local runs with no AWS, and `load`, which needs RUN_ID and the DSQL and role env vars ([data_load/__main__.py:99-141, 154-208, 278-288](../../../data_load/__main__.py)).
- Inside curate:
  - load the 13 tables to an on-disk DuckDB;
  - `check_evidence`;
  - personas, profile and defect classes;
  - cohort selection and snapshot;
  - `apply_rules`;
  - re-profile and `select_clean`;
  - `_assemble`;
  - `_check` (invariants on the clean set, gates, lost defects, disjointness, `repair.check_links`);
  - `_compare` with `expected.json` on full default-size runs;
  - write Parquet.

  ([data_load/curate.py:49-107, 133-174](../../../data_load/curate.py).)
- The guard: `check_evidence` fails if any input `customers.customer_id LIKE 'EVL-%'` ([data_load/curate_rules.py:51-73](../../../data_load/curate_rules.py)), and a unit test pins the message ([tests/unit/test_data_load_curate_rules.py:96-102](../../../tests/unit/test_data_load_curate_rules.py)). The spec also lists "no `EVL-` ID" as a whole-output check ([curate spec:230](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)), but `_check` has no such test. The only `EVL` code in `data_load/` is the input check (grep).
- E11: "The `EVL-` ID prefix is reserved for the harness's injected clones. Clones can live in `public` next to real customers, isolated by ID, with no tool change", chosen over a separate eval schema ([curate spec:52](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)). E2 explains why a new schema was rejected: all 7 tool SQL files would change ([:43](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)). E8: no rare-scenario quotas, because "the evaluation harness injects rare situations into clones" ([:49](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)).
- `_compare` raises when rows per table differ from `expected.json` → `curation.rows` on a full default run, for example customers 1,659 and transactions 84,544 ([curate.py:96-98, 167-174](../../../data_load/curate.py); [data_load/expected.json:40-54](../../../data_load/expected.json)).
- Load:
  - drops and recreates every table, because "DSQL has no TRUNCATE" ([data_load/dsql.py:32-37](../../../data_load/dsql.py));
  - re-applies roles and grants ([:40-73](../../../data_load/dsql.py));
  - bulk-loads with `aurora-dsql-loader ... --schema public --on-conflict do-nothing --verify count` ([:111-118](../../../data_load/dsql.py));
  - rebuilds three async indexes ([data_load/schema.sql:128-131](../../../data_load/schema.sql)).
- The tools see only `public`:
  - every tool SQL uses unqualified table names, and no tool sets `search_path` (grep over `gateway/tools`);
  - the loader writes `--schema public` ([dsql.py:113](../../../data_load/dsql.py));
  - `ll_read` gets SELECT on all tables in `public` ([schema.sql:118](../../../data_load/schema.sql)).
- No customer id format is enforced anywhere:
  - the pre-token Lambda returns whatever string is mapped to the Cognito sub ([infra-cdk/lambdas/pretoken-v3/index.py:79-101](../../../infra-cdk/lambdas/pretoken-v3/index.py));
  - tools only strip and uppercase it ([block_credit_card.py:162-172](../../../gateway/tools/block_credit_card/block_credit_card_lambda/application/use_cases/block_credit_card.py));
  - Cedar compares the input id with the token tag ([policy.cedar:5-15](../../../gateway/policies/policy.cedar));
  - a grep for `CLI-` patterns in agent, gateway, infra and scripts found no validation.
- Id lengths: `customer_id`, `product_id`, `transaction_id` and `complaint_id` are `varchar(30)` ([schema.sql:9, 26, 54, 94](../../../data_load/schema.sql)).
- One tool reads across customers: `resolution_estimate.sql` aggregates every customer's Transactions claims of the last 365 days that have `resolution_days` ([gateway/tools/open_claim/.../resolution_estimate.sql:15-23](../../../gateway/tools/open_claim/open_claim_lambda/queries/postgresql/resolution_estimate.sql)). `daily_exchange_rates` is a shared dimension ([explain_transaction.sql:38-42](../../../gateway/tools/explain_transaction/explain_transaction_lambda/queries/postgresql/explain_transaction.sql)).
- Measured durations of the first curated run (2026-10-03): Ingest 2.2 min, Transform 4.7, **Curate 1.9**, **Load 1.2**, ReadCheck 0.1, whole run **10.0 min**; about 9 CodeBuild build-minutes, ≈ $0.14 ([curate spec:319-336](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)). Rerunning curate then load for the same run takes about 5 min ([:307](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)). On a laptop, transform takes about 7 min and curate about 4 ([curated-customers.md:58](../../docs/analysis/2026-10-03-curated-customers.md)). The "~10 min" figure is therefore the **whole** pipeline, not curate alone.
- DSQL changes at most 3,000 rows per transaction ([docs/LEDGERLENS_PRODUCT_DESIGN.md:868, 1049](../../../docs/LEDGERLENS_PRODUCT_DESIGN.md)).
- Local rehearsal needs the organizer CSVs under `datathon/data` ([curated-customers.md:52-56](../../docs/analysis/2026-10-03-curated-customers.md)). That folder is not in the worktree (the `datathon/` listing shows only analysis, docs, reports, research_notes). The unit-test fixture builds a tiny in-memory bank, with `good()`, `customer()`, `card()` and `charge()` helpers, which mutation-op tests could reuse with no data ([tests/unit/curate_fixtures.py:1-12, 51-144](../../../tests/unit/curate_fixtures.py)).

### Inferences
- **Insertion options** (my design inference):
  - **(A) Inside curate**, after `_assemble`. `check_links` would then validate the clones, but `_compare` would fail on the full run unless `expected.json` is re-pinned or the clones are counted separately. The spec's "no `EVL-` in output" line would also need to change. Every change to the clones also means re-running curate and load (about 3–5 min) with a roughly 2-min tool outage, and it resets the personas.
  - **(B) A separate `evl` command after load** (preferred). Read the curated rows of N source customers (curated Parquet, or DSQL as admin). Write `EVL-` copies with re-prefixed ids across the 7 customer-linked tables (`LINKED`, [curate.py:25-34](../../../data_load/curate.py), plus transcripts and surveys via interaction). Apply the ops. Append in batches of at most 3,000 rows, with no DROP. A reset is `DELETE … WHERE customer_id LIKE 'EVL-%'` per table, as admin, then re-append. Real personas and the demo login are never touched.
  - **(C) Local DuckDB copies with sandbox tool doubles**, for graders and the oracle only. This doesn't test the deployed agent.
- Id prefixes fit: `EVL-` + a 12-character suffix is 16 characters. `EVL-TRX-…` and `EVL-CMP-…` are 28 (base ids are 24), `EVL-PRD-…` is 20. All are within `varchar(30)`.
- Clones are isolated from every tool query except `resolution_estimate`. Cloned complaints with `resolution_days` would shift the estimate slightly, so either drop `resolution_days` on cloned complaints or accept the shift.
- Time for (B): a script plus round-trip unit tests in about 3–4 h, plus the append run. It fits 2026-10-05 only if limited to the 2–4 ops that personas don't already cover (see Q4). It needs AWS writes, which the team's own rules gate behind the branch's code review. It also needs one Cognito login, or one map entry, per clone (eval-on-hold doc L8, line 127).

### Gaps
- Where a clone or append script would get the source rows without the organizer data: from S3 `curated/<run-id>/` (allowed for the team, not in this research) or from DSQL as admin. Neither was exercised.
- Whether `aurora-dsql-loader` can append a Parquet file into an existing table without the CLI's `apply_schema` step. The flag set suggests so, but it is untested.

## Q4. Which of the ten mutation ops are already covered naturally, which need new rows, and the tool-window constraints

### Takeaway
Six of the ten ops have a natural, documented carrier:
- `inject_charge` (Pending P02, Reversed P03, Declined P01/P05/K07, fraud-Approved P07);
- `set_card_status(Blocked)` (P10);
- `active_but_expired` (K02 `CLI-0IHHK5P7SSWR`);
- `add_second_card(same merchant)` (P04);
- `open_unrecognized_case` (P08);
- `remove_txn`, which needs no rows: it is just the user's turn.

`stale_case` exists as K13 but is invisible to the tools; its visible cousin is K12. Only **`inject_duplicate`, `inject_reversal_pair` and `inject_text`** truly need new rows. A 72 h-window fraud charge also needs new rows if a session-opening fraud case is wanted.

### Cited Findings
- The ops and their policy consequences ([datathon/reports/Agent evaluation signal on AWS.md:64-82](../../reports/Agent%20evaluation%20signal%20on%20AWS.md)). Rule: keep timestamps consistent with the 72 h and 24 h session windows, the 30-day list default and the fixed `AS_OF` ([:80](../../reports/Agent%20evaluation%20signal%20on%20AWS.md)).
- Natural scenario counts in the 1,500 clean customers:

  | Scenario | Customers |
  |---|---:|
  | Two or more usable cards | 1,224 |
  | Past-due usable credit card | 467 |
  | Foreign charge in 30 d | 216 |
  | Blocked or Suspended credit card | 102 |
  | Reversed in 30 d | 61 |
  | Decline 05/14/51 in 7 d | 55 |
  | Pending in 7 d | 30 |
  | Code-54 decline in 30 d | 25 |
  | Digital event in 24 h | 17 |
  | Open unrecognized-charge case | 7 |
  | Fraud-flagged approved charge in 30 d | 3 |

  ([curated-customers.md:141-155](../../docs/analysis/2026-10-03-curated-customers.md).) These are customer counts. Only the personas and showcases have documented ids.
- Windows by tool:
  - session transactions: credit cards, `transaction_date ≥ as_of − 72 h`, with history to 90 days for the baseline ([session_recent_transactions.sql:46-58](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_recent_transactions.sql));
  - signals: 24 h ([session_digital_signals.sql:40-42](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_digital_signals.sql));
  - list: `process_date BETWEEN date_from AND date_to`, defaulting to 30 days ([list_card_transactions.sql:54](../../../gateway/tools/list_card_transactions/list_card_transactions_lambda/queries/postgresql/list_card_transactions.sql));
  - fraud sweep: 30 days on `transaction_date` ([fraud_card_sweep.sql:49-51](../../../gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/queries/postgresql/fraud_card_sweep.sql));
  - classify: 72 h, plus 30-day approved charges above 30 ([call_reason_transactions.sql:69-70](../../../gateway/tools/classify_call_type/classify_call_type_lambda/queries/postgresql/call_reason_transactions.sql));
  - explain: `transaction_date ≤ as_of` only ([explain_transaction.sql:46](../../../gateway/tools/explain_transaction/explain_transaction_lambda/queries/postgresql/explain_transaction.sql)).
- Classify skips charges named in an open claim's description, parsed from `" | tx: "` ([call_reason_transactions.sql:22-27, 57-76](../../../gateway/tools/classify_call_type/classify_call_type_lambda/queries/postgresql/call_reason_transactions.sql)), which is the format `open_claim` writes ([open_claim.py:165](../../../gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py)).
- Strings returned to the model, and so open to `inject_text`:
  - `merchant_name` (session, list, explain, fraud) and `transaction_city` (list, explain);
  - `page_title`, `ip_city` and `ip_country` (signals) ([session_digital_signals.sql:34-36](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_digital_signals.sql)).

  `complaints.description` is not returned by `open_cases` ([session_open_cases.sql:24-33](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_open_cases.sql)). `merchant_name` is `varchar(150)` ([schema.sql:57](../../../data_load/schema.sql)). A Bedrock guardrail now sits in front of the agent, so injection cases test the guardrail and the agent together (eval-on-hold doc, line 132).

| Op | Natural carrier (documented) | Window fit | New rows? |
|---|---|---|---|
| `inject_charge` Pending / Reversed / Declined | P02 (Pending, 72 h), P03 (Reversed, 72 h), P01 (51, 72 h), P05 (14, outside 72 h), K07 `CLI-47BQDE276OXT` (54, 72 h) | Covers both the in-session and list-only paths | No |
| `inject_charge` Approved + fraud flag | P07 (62.39, 05-31): 30-day path only | No fraud-flagged charge inside 72 h is documented | Only for a 72 h fraud variant |
| `inject_duplicate` | None (P04's two Mercado Central charges differ in amount and currency) | — | **Yes** |
| `inject_reversal_pair` | P03 has the Reversed row only, with no original in its 30-day list | — | **Yes** |
| `set_card_status(Blocked)` | P10 card 7718; a block call returns `already_blocked: true` ([block_credit_card.py:150-151](../../../gateway/tools/block_credit_card/block_credit_card_lambda/application/use_cases/block_credit_card.py)) | Products have no window | No |
| `active_but_expired` | K02 `CLI-0IHHK5P7SSWR` card 1498 (approval on 05-19). The clean set excludes it by design (G7, [curate_select.py:121](../../../data_load/curate_select.py); C8 reissue) | List default covers 05-19 | No (cohort); yes for a "clean otherwise" variant |
| `add_second_card(same merchant)` | P04 (2218 and 5384) | List only | No |
| `open_unrecognized_case` | P08 (`CMP-FHCLR8TGWMBD0YFOCLYS`, In Process) | No age window | No |
| `stale_case(Resolved, no closing_date)` | K13 `CLI-3M640ZWWWMO6`, but **filtered out** by the open-case filter; visible cousin K12 `CLI-16VESRAA8DYC` (open over 60 d) | — | Op is moot until a tool shows non-open cases |
| `inject_text` | None | Must sit in `merchant_name` or `transaction_city` within the window | **Yes** |
| `remove_txn` | Any persona: the user describes a charge that isn't in the records | — | No (utterance only) |

### Inferences
- A one-day harness can cover the report's "card count", "transaction status", "data defect" and "session state" factors entirely from personas plus documented cohort ids. `EVL-` work can be limited to three ops, plus clones of P07 so that write cases are repeatable.
- When a clone needs an in-session variant, set `transaction_date` within (2026-06-14 23:59:59, 2026-06-17 23:59:59] and `process_date` ≤ 2026-06-17. For a list-only variant, keep `process_date` in [2026-05-18, 2026-06-17] and `transaction_date` before 2026-06-14 23:59:59.

### Gaps
- Whether the dataset has natural same-merchant, same-amount duplicate charges, or original-plus-reversal pairs, among the 1,500 is not documented.

## Q5. State drift from the write tools: who is left changed, what to restore, and existing reset mechanisms

### Takeaway
A correct run changes only **P07**:
- `products` `PRD-Z3Y8BK8CKUTN`: `product_status` goes from `'Active'` to `'Blocked'`, and `last_updated` is set to as_of;
- one inserted `complaints` row with a deterministic id, `CMP-CEBEOA5RFQEVO7BQWS2F` for a fraud claim (computed).

The next trial then sees a blocked card, an open case and no `FRAUD_SUSPECTED`: a different case. Wrong runs can also touch P04 (block after clarify), P07's 4391, or P08 (duplicate claim). The only existing reset is re-running the `load` stage for the last run. It drops and reloads every table, with about 2 min of tool outage. There is no dedicated reset stage. P07 was the recommended smoke-test customer and was in the PR #15 persona eval, so its current state is unknown.

### Cited Findings
- `block_credit_card` updates `products` to `product_status = 'Blocked'` and `last_updated = now (AS_OF)`, guarded by `product_status NOT IN ('Blocked', 'Closed')` ([gateway/tools/block_credit_card/.../block_credit_card.sql:15-21](../../../gateway/tools/block_credit_card/block_credit_card_lambda/queries/postgresql/block_credit_card.sql)). The block reason is stored only in CloudWatch Logs ([block_credit_card.py:96-104](../../../gateway/tools/block_credit_card/block_credit_card_lambda/application/use_cases/block_credit_card.py)).
- `open_claim` inserts into `complaints`:
  - `case_type 'Claim'`, `category 'Transactions'`, `reception_channel 'Web'`;
  - `status 'Open'`, `sla_breached false`;
  - `creation_date` = as_of;
  - `description "<statement> | tx: <ids>"`.

  ([insert_claim.sql:24-33](../../../gateway/tools/open_claim/open_claim_lambda/queries/postgresql/insert_claim.sql); [open_claim.py:139-184](../../../gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py).) The id is `CMP-` plus 20 base32 characters of `sha256(customer|type|product|currency|sorted tx ids)`, so a repeat raises 23505 and returns `already_existed: true` ([open_claim.py:219-241](../../../gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py)).
- Ids computed locally with that function:
  - P07 fraud on `TRX-23BIJAU4GL46ATPW9STY` / `PRD-Z3Y8BK8CKUTN` / USD → `CMP-CEBEOA5RFQEVO7BQWS2F`;
  - P07 dispute → `CMP-Z2VK2FEL6SFHCQBZCLMB`;
  - a wrong P08 fraud claim on `TRX-OW0S5SQC8JI9MJDLTKU1` / `PRD-91WQPO82YRER` / COP → `CMP-WX2WMJKBYEMGBJHQHLEF`.

  (Computation, not data access. The same statement text is not required, because the statement isn't in the key.)
- Downstream effects on later trials:
  - the new claim is "open" for `get_session_context` ([session_open_cases.sql:37-40](../../../gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_open_cases.sql)) and for classify (`OPEN_CASE_FOLLOWUP`);
  - its transaction drops out of classify's fraud candidates ([call_reason_transactions.sql:71-76](../../../gateway/tools/classify_call_type/classify_call_type_lambda/queries/postgresql/call_reason_transactions.sql));
  - the blocked card returns `already_blocked: true` on a second block;
  - the eval-on-hold doc notes that pass^3 on write cases is wrong without a reset (L5, [line 124](../../docs/analysis/2026-10-03-eval-observability-on-hold.md)).
- `human_agent_hand_off` writes nothing to DSQL (SNS only, runs outside the VPC) ([docs/superpowers/specs/2026-10-03-write-tools-design.md:38](../../../docs/superpowers/specs/2026-10-03-write-tools-design.md)). Its summary goes by email to `admin_user_email` (W7, [:539](../../../docs/superpowers/specs/2026-10-03-write-tools-design.md)), so every eval hand-off sends an email.
- Grants: `ll_write` has SELECT on products, transactions and complaints; UPDATE on products; INSERT on complaints; **no DELETE** ([schema.sql:120-126](../../../data_load/schema.sql)). A row-level restore must run as admin.
- Restore values for P07: `product_status` was `'Active'` ([curated-customers.md:367-368](../../docs/analysis/2026-10-03-curated-customers.md); [personas.json:41-46](../../../data_load/personas.json)). The original `last_updated` is not documented. C6 clamped 25,113 products' `last_updated` to as_of ([curated-customers.md:69](../../docs/analysis/2026-10-03-curated-customers.md); [expected.json:32](../../../data_load/expected.json)). No read tool returns `last_updated`; it is used only to order the de-duplication ([list_credit_cards.sql:41](../../../gateway/tools/list_credit_cards/list_credit_cards_lambda/queries/postgresql/list_credit_cards.sql)).
- Existing reset mechanisms:
  - "No reset stage. Writes stay until the next full load" ([write-tools spec:40](../../../docs/superpowers/specs/2026-10-03-write-tools-design.md)). W3: "Reload before the final demo if a rehearsal touches P03" ([:535](../../../docs/superpowers/specs/2026-10-03-write-tools-design.md)).
  - The write-tools plan's Task 12 recommended **P07** (`CLI-EX6BOAOEFZHQ`, card 4497, `TRX-23BIJAU4GL46ATPW9STY`) for the smoke test: block twice, `open_claim` twice, hand-off once. It restores by re-running CodeBuild `STAGE=load` with `RUN_ID` = the last SUCCEEDED pipeline execution, then checks that 4497 is Active again. It warns that tools see missing tables for about 2 minutes ([docs/superpowers/plans/2026-10-03-write-tools.md:6918-6920, 6953-7009](../../../docs/superpowers/plans/2026-10-03-write-tools.md)).
  - The load itself drops and recreates every table ([dsql.py:32-37](../../../data_load/dsql.py)) and took 1.2 min ([curate spec:328](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md)).
- Known test state: the PR #15 persona eval exercised P07's claim path ("Priority high follows a High claim … (P07)", `git show bc0787a`). Its transcripts are not in the repo (eval-on-hold L11, [line 130](../../docs/analysis/2026-10-03-eval-observability-on-hold.md)). `git log --grep` finds no commit recording a reload or restore after it.

**Rows a trial can change, and their restore values.**

| Persona | Trigger | Table / key | Columns changed | Restore |
|---|---|---|---|---|
| P07 (expected) | block 4497 | `products` `PRD-Z3Y8BK8CKUTN` | `product_status` → Blocked; `last_updated` → 2026-06-17 23:59:59 | `product_status = 'Active'` (original `last_updated` unknown and functionally unused) |
| P07 (expected) | fraud claim | `complaints` `CMP-CEBEOA5RFQEVO7BQWS2F` (dispute variant `CMP-Z2VK2FEL6SFHCQBZCLMB`) | new row | DELETE as admin |
| P07 (error) | block 4391 | `products` `PRD-I7CW038INJHY` | as above | `'Active'` |
| P04 (error, or after clarifying) | block 2218 or 5384 | `PRD-TVC3HHMH0II0` / `PRD-VLRZ7201XLV1` | as above | `'Active'` |
| P08 (error) | duplicate claim | `complaints` `CMP-WX2WMJKBYEMGBJHQHLEF` (fraud on `TRX-OW0S…`) | new row | DELETE |
| P10 | block 7718 | none (guarded; already Blocked) | — | — |
| Any | `open_claim` on another charge | `complaints`, id from the content hash | new row | DELETE |

### Inferences
- Detect drift after each trial by snapshotting `product_status` for the persona's cards, not by `last_updated`, since C6 makes `last_updated = as_of` common. For claims, look for `creation_date = '2026-06-17 23:59:59' AND description LIKE '% | tx: %'`. Organizer descriptions presumably lack that marker; this is unverified.
- A targeted admin restore (one UPDATE plus one DELETE) is seconds per trial and causes no outage. A load-stage reload restores everything but takes the tools down for about 2 min, so use it only once, before the final demo.
- Before any eval run, verify P07 read-only:
  - `list_credit_cards` should show 4497 Active;
  - `open_cases` should be empty;
  - classify should show `FRAUD_SUSPECTED`.

  If not, the PR #15 eval or the smoke test left it changed.

### Gaps
- P07's current live state, and whether Task 12's restore was ever run: unknown without an AWS read.
- P07's original `products.last_updated` value.

## Q6. Languages: Spanish versus Portuguese (Brazil) coverage

### Takeaway
Every curated customer is Mexican, Colombian or Argentine, so Spanish-speaking. There are no Brazilian customers and no Portuguese text in the data. Portuguese coverage is only P05, a Mexican customer whose test turns are written in Portuguese, with a Brazilian charge. Any pt-BR stratum must come from translated user turns over the existing customers, audited by a fluent reader.

### Cited Findings
- The curated cells are 3 countries × 4 segments: Argentina, Colombia and México ([curated-customers.md:124-137](../../docs/analysis/2026-10-03-curated-customers.md)). The home currency and legal deadlines are defined only for those three ([curate_rules.py:16-25](../../../data_load/curate_rules.py)).
- DEC-11: "The data has zero Portuguese demand: customers are MX, CO and AR only; Brazil transactions are in USD/COP/ARS". The plan is a labelled synthetic Portuguese persona validated by a fluent reviewer ([2026-09-26-data-findings-and-workflow-decision.md:362-366](../../docs/analysis/2026-09-26-data-findings-and-workflow-decision.md)). The transcripts hold zero Portuguese ([:17](../../docs/analysis/2026-09-26-data-findings-and-workflow-decision.md)).
- The prompt says: "Reply in the language the customer writes in (Spanish, Portuguese or English) … If their message is too short to tell, use their country's language: Portuguese for Brazil, Spanish otherwise" ([agent/ledgerlens/tools/system_prompt.py:162-164](../../../agent/ledgerlens/tools/system_prompt.py)). With no Brazilian customer, the fallback is always Spanish.
- P05's expected outcome is "answer in Portuguese; explain the charge in Brazil" ([personas.json:29-33](../../../data_load/personas.json)). The design review notes that the language rule is prompt-only, that language and jurisdiction aren't split (it is a Mexican account), and that Portuguese-speaking fraud specialists number 4 / 2 / 1 / **0 at night** ([docs/handoffs/2026-10-04-agentic-design-review.md:99](../../../docs/handoffs/2026-10-04-agentic-design-review.md); F42 in [2026-09-26 doc:104](../../docs/analysis/2026-09-26-data-findings-and-workflow-decision.md)).
- The report treats ES↔pt-BR translation as an invariance edit: only the reply language flips, while the exit and tool calls stay fixed. It warns that synthetic data is unreliable for dialects, so a native reader must audit pt-BR ([Agent evaluation signal on AWS.md:115, 137](../../reports/Agent%20evaluation%20signal%20on%20AWS.md)).

### Inferences
- The Spanish dialects available through personas are Argentine (P02, P03, P09, where voseo variants apply), Colombian (P01, P04, P08) and Mexican (P05–P07, P10). pt-BR is a turn-language factor, not a customer factor. Any persona can be run with Portuguese turns under the same label, plus a check that the reply is in Portuguese, which can be done in code with a language-ID check.
- A short Portuguese message from a Mexican customer is the edge case: by the prompt's fallback, the expected reply is Spanish. That is a deterministic DIR case worth one test.

### Gaps
- No repo source states which language-ID method or reviewer will validate Portuguese replies for the deadline.
