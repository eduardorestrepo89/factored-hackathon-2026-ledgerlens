# LedgerLens agentic design review (2026-10-04)

Read-only review by a research agent. It edited, committed and deployed nothing, made no AWS calls, and opened no organizer PDF. Data probes ran only against the local raw `datathon/analysis/bank.duckdb`, read-only.

**Tags:**
- **[V]** verified in code, docs or data during the review.
- **[J]** the reviewer's judgement.
- **[W]** web source (section 6).

**State it reviewed:** prompt **v7** (uncommitted), with the "CONFIRMATION BUTTONS" section and `tools/confirmation_hook.py`, a Strands interrupt for `open_claim` and `human_agent_hand_off`. It also saw the frontend `ConfirmCard.tsx`, which has since been reverted and described in `2026-10-04-confirmation-buttons-frontend.md`.

---

## 1. Flow map (target, as built)

```
Customer (React, Cognito) ── prompt + runtimeSessionId ──► AgentCore Runtime invocations()
 0 [CODE]  JWT sub → M2M token; the pre-token Lambda adds customer_id (USER_CUSTOMER_IDS_MAP)
 1 [CODE]  Agent built: STM window 30, Guardrail (latest user msg only),
           hooks CustomerIdHook → ConsentHook → ConfirmationHook (v7)
 2 [CODE]  Once per session: get_session_context ∥ classify_call_type → agent.state
           → <session_context> in the system prompt. NEVER refreshed afterwards.
 3 [MODEL] Opening: picks reason #1 and how to word it
 4 [MODEL] Finds the charge: list_card_transactions filters
 5 [MODEL] explain_transaction ── [LAMBDA] decline-meaning table, fx row, habit,
                                  app conflict, contradicts_card_state (K07 only)
 6 [MODEL] Decides when the fraud protocol starts and its order (PROTECT→REVIEW→CLAIM)
     block_credit_card: [CODE] ConsentHook heuristic (offer named last4 + explicit "yes")
     open_claim:        [UI-CLICK] Yes/No interrupt (v7)
 9 [MODEL] Hand-off reason, priority and free-text summary → [UI-CLICK] Yes/No (v7)
   Every Gateway call:
     [CODE]   customer_id overwritten from the token
     [CEDAR]  r1 linked customer, r2 same customer, r3 customer_confirmed==true (a MODEL-set boolean)
     [LAMBDA-SQL] owner filter; write ids hashed from content (idempotent);
                  claim priority High above USD 500
10 [LAMBDA] human_agent_hand_off validates enums and makes an HO- id; it stores nothing
11 [UI]    The frontend finds the hand-off result in the stream → split screen.
           The bot is never called again (ChatInterface.tsx:94).
           "Laura"'s messages stay in the browser only (ChatInterface.tsx:283).
```

**Where determinism lives today [V]:**
- identity and `customer_id` (code, Cedar and SQL);
- the session start;
- reason ranking and fraud bands, decline meanings, FX and habit (Lambda code);
- idempotent write ids and the USD 500 priority rule;
- the consent heuristic for blocks, and the Yes/No buttons for claims and hand-offs;
- stripping leaked model markup from the stream.

**What the model decides:**
- the opener;
- when the fraud protocol starts;
- tool choice and filters;
- which transactions go into a claim, and `claim_type`;
- the hand-off reason, priority and the whole summary;
- every deadline or estimate it tells the customer.

**Holes in the flow [V]:**
- **Stale context after writes.** `apply_session_context` only fetches when `agent.state` is empty (`session_context.py:99-104`). After a block, the prompt still shows the card as Active and still lists FRAUD_SUSPECTED. A new claim never appears in `open_cases`.
- **Cedar rule 3 checks a value the model sets.** Now that the buttons exist, that boolean proves nothing.
- **The hand-off payload has no provenance.** It is model free text, and the desk shows it as "Assistant summary".
- **Nothing is persisted after a hand-off.** Reloading the page loses the case.

---

## 2. Redundancy table (9 tools)

| Tool | What it does / data touched [V] | Overlap [V] | Verdict [J] |
|---|---|---|---|
| `get_session_context` | Snapshot built from customers (5 columns), products (credit cards), transactions (72 h + 4 flags), digital_events (24 h signals) and complaints (open cases). Called by code. | Its cards section is a copy of `list_credit_cards.sql` (the SQL comment says so). Its open cases are the same filter classify's `call_reason_cases` uses, and FAILED_ACTION is the same as classify's app-error query. Design doc §7 says it reads call_center_interactions and daily_exchange_rates; the SQL doesn't. | **Make it deterministic code.** Hide it from the model with Strands `MCPClient(tool_filters=…)` (present in 1.32 [V]), and bootstrap through a second, unfiltered client. Later, merge it with classify into one `session_bootstrap` Lambda. |
| `classify_call_type` | Ranks contact reasons from transactions (30 d, `fraud_score` bands), products, complaints and digital_events | Its fraud bands (50/30) are copied in `transaction_fraud_detection` (`fraud_bands.py` in both, "keeps its own copy"). Its cards and cases duplicate the session snapshot. | **Merge with #1 and keep it code-only.** Keep the ranking logic. |
| `list_credit_cards` | products | Same SQL as the session snapshot's cards | **Keep.** It is the only fresh read after a write, and the source for "which card?". |
| `list_card_transactions` | transactions + products, with filters | Overlaps the session's 72 h list | **Keep, and add `transaction_type`.** Without that column, the REVIEW step shows P07's Web "Withdrawal" and Payments as "charges". |
| `explain_transaction` | transactions, products, daily_exchange_rates (`sell_rate`), digital_events ±2 h, 90-day habit | Its "usual" (p10–p90, same currency) differs from the session's `above_usual_amount` (p95, USD), so the two can disagree [J]. | **Keep (core).** Make it the single owner of "is it usual". |
| `transaction_fraud_detection` | Bands `transactions.fraud_score` | Same bands and window as classify's FRAUD_SUSPECTED / UNRECOGNIZED_CHARGE_REVIEW. Prompt v7 never tells the model to call it and forbids mentioning verdicts (`system_prompt.py:76`, PRIVACY). | **Drop it from the model's tool list.** Move the band into code: claim priority or queue, and the hand-off evidence a human sees. Keep the Lambda, since Cedar lists its action. |
| `block_credit_card` | products (find, then UPDATE) | None | **Keep.** It only covers credit cards, though debit cards exist for P04, P05, P06, P09 and P10. There is no audit row, although design §14 promises one. |
| `open_claim` | transactions; INSERT into complaints; resolution estimate | Deduplicates only on its own content hash, not against existing cases | **Keep, and fix the bugs below.** |
| `human_agent_hand_off` | Touches no data: validates enums and hashes an id; no AWS call | None | **Keep it on the Gateway**, because it is the event a temporal policy needs to see (proposal 10). Build its payload in code and persist it. |

**Bugs found [V]:**
- **Disputes get an invalid category.** `open_claim` files a `dispute` as category `'Transactions'` with subcategory `'Cobro indebido'` (`insert_claim.sql`). In the data, 'Cobro indebido' exists only under category **Fees** (12,194 rows; none under Transactions). Dispute claims therefore break the taxonomy, and their resolution estimate is always null.
- **The resolution estimate is probably always null in the demo [J, needs one query to check].** `resolution_estimate.sql` needs at least 20 rows of Claim / Transactions / Cargo no reconocido from the last 12 months. The raw data has 236 such rows out of 67,095 complaints, but the curated database holds only 778 complaints (`expected.json`), so it is likely below 20. Where it does produce a figure, C11 sets `resolution_days` equal to the synthetic legal deadline, so "usually ~N days" mostly repeats that deadline.

**Dead weight [V]:**
- `tools/mcp_registry.py` (363 lines) plus `test_mcp_registry.py` and the `mcp_registry` config block; the feature is disabled.
- The long-term-memory retrieval path, which is off.
- The FAST template docs that the eval on-hold doc flags as stale.

---

## 3. Gaps by persona and defect class

| Persona | Status [V] | Gap |
|---|---|---|
| P01 decline 51 | Covered | None of note |
| P02 pending | Covered (status) | No settlement data; fine |
| P03 reversed + app signal | Covered | [J] The privacy rule bans mentioning app activity, so the opener must name the reversal, not the app view |
| P04 which card | Prompt-only | No code-rendered card picker |
| P05 Portuguese, Brazil charge | The language rule is prompt-only. USD card and USD charge, so `fx` is null. | No split between language and jurisdiction (it is a Mexican account). The hand-off ignores the staff roster: active Portuguese-speaking fraud specialists are Morning 4, Afternoon 2, Rotating 1 and **Night 0** [V raw]. |
| P06 out of scope | Prompt boundary | No deterministic tripwire or abstention |
| P07 fraud | Works end to end | **Card blocks** still rely on a text heuristic, while claims and hand-offs have buttons. The context is stale after the block. Mexican rights aren't stated (90 days to file, 45-day ruling, may withhold payment, no credit-bureau report: LTOSF art. 23 [W]). The estimate is likely null. |
| **P08 open case** | **Poorly covered** | `open_cases` has no assignment, first-response or deadline fields, and no tool reads a single case. `open_claim` can file a new claim (e.g. for the 06-17 Super Ahorro charge) while CMP-FHCLR8TGWMBD0YFOCLYS is still open (Cargo no reconocido, In Process, assigned 06-08, first response 06-10 [V raw]). Unused history: a **Técnico phone call on 2026-05-24, unresolved, requires_followup, CSAT 3**, and an App Queja on 04-24 [V raw]. Under CO-PQR (C11: 21 days) the deadline is 2026-06-29, 12 days left at as_of. |
| **P09 contradiction** | Covered through `contradicts_card_state` | The hand-off carries no structured record of the conflict. Unused: an **unresolved Queja call on 04-27, requires_followup, CSAT 2** [V raw]. |
| P10 card not active | Covered (status only) | Fine |

**Defect cohort [V]:** only K07 is flagged at runtime. The others reach the model raw:

| Class | What the model sees |
|---|---|
| K01 | `customer_status` is in the profile, but no rule uses it |
| K02 | `expiration_date` is returned, but nothing checks it against "Active" |
| K03 / K04 | A null limit, or negative `available_credit` |
| K05 | A pending charge older than 30 days, shown as just "pending" |
| K09 | `list_card_transactions` returns the raw `'Mexico'` spelling, while the session query folds accents |
| K11, K12–K15 | Not flagged |
| K17 | The profile omits contact fields, so the agent can't know a hand-off has no channel |

**Unused data [V]:**
- Whole tables: call_center_interactions, satisfaction_surveys, service_agents, branches, campaign_sends and marketing_campaigns (these two stay out per DEC-8), and call_transcripts (templated junk, D34).
- Columns: `complaints.assignment_date`, `first_response_date`, `assigned_agent_id`, `reception_channel` (717 'Regulator' rows raw) and `is_repeat_complainer`; `transactions.transaction_type`; debit-card products; `daily_exchange_rates.buy_rate` and `exchange_rate`.

---

## 4. Proposals, ranked by judge impact × feasibility by 2026-10-05

| # | Proposal | Type | Impact | Feasibility | Score |
|---|---|---|---|---|---|
| 1 | Evidence-ledger case file | Deterministic check + UI | 5 | 4 | 20 |
| 2 | Open-case clock + duplicate-claim guard + rights card | Deterministic check + UI | 4 | 5 | 20 | - This one is good
| 3 | Record-integrity annotator | Deterministic check | 4 | 4 | 16 |
| 4 | Promise checker on the human's composer | UI mechanic, deterministic | 3 | 5 | 15 |
| 5 | Prior-contact context + repeat-contact priority floor | Tool + rule | 4 | 3 | 12 | - This one looks good
| 6 | Roster-aware routing | Deterministic tool | 3 | 4 | 12 |
| 7 | Four-eyes checker sub-agent | Multi-agent | 3 | 3 | 9 |
| 8 | Wallet lockdown | Tool + policy | 3 | 3 | 9 |
| 9 | No-LLM safe mode for the fraud journey | Workflow | 4 | 2 | 8 |
| 10 | Dogwood rule: AI writes end at the hand-off | Cedar policy | 4 | 2 | 8 |
| 11 | Gateway RESPONSE-interceptor "data firewall" | Platform check | 4 | 2 | 8 |
| 12 | Legal clock as a durable workflow | Workflow (stretch) | 3 | 1 | 3 |

**Build first for 2026-10-05: 1, 2 and 3.**
- All three are agent-side hooks plus a prompt change (v8; the test pins the hash) and an AgentDesk panel.
- They need no Lambda, Cedar or CDK change, and they share one ledger hook.
- Together they take about 1.5 person-days. Minimum cuts if time is short: proposal 2 as a hook only (~2 h), proposal 3 with four classes (~3 h), proposal 1 without the LLM checker (~4 h).
- Coordinate with whoever edits `system_prompt.py` and the hooks.

### 1. Evidence-ledger case file (deterministic check + UI)
- **What it does:**
  - An `AfterToolCallEvent` hook records facts from each tool result into `agent.state["ledger"]`: transaction ids and amounts, card last 4 digits and status, the block result, claim ids and conflicts. (`result` is writable in 1.32 [V].)
  - When the hand-off runs, code builds the case file in three parts: `verified_facts` (with source tool and ids), `actions_taken`, and `customer_said` (the customer's verbatim lines).
  - A numeric check flags any amount, last-4, id or date in the model's summary that isn't in the ledger, after normalising locale formats.
  - AgentDesk shows "Verified by records" chips separately from "Customer says". The case file is streamed as an extra event, so no Lambda change is needed.
- **Data:** whatever the tools returned (transactions, products, complaint ids).
- **Why it's new:** prior research asked for a payload built by code; this is the concrete mechanism, with provenance on each line. It directly fixes the review finding that the hand-off summary can carry false claims.
- **Effort:** 0.5–0.75 day.
- **Risks:** stream event ordering; ES/PT number formats.
- **Demonstrates:** P07, P09.

### 2. Open-case clock + duplicate-claim guard + rights card (deterministic check)
- **What it does:**
  - **Clock:** at session start, code adds `legal_deadline` and `days_left` to each open case. It uses the customer's country and **the same C11 table the curate stage uses** (`data_load/curate_rules.py`: AR-CLAIM 14, CO-PQR 21, MX-UNE 42 days), with `as_of` from the snapshot. The deadline the agent states can never disagree with the one the data pipeline enforced.
  - **Guard:** a `BeforeToolCallEvent` hook cancels `open_claim` when an open 'Cargo no reconocido' case exists. Its message tells the model to give that case's status and deadline and offer a person.
  - **Rights card:** after a claim, code renders the country's rights from a template carrying rule ids.
    - Mexico: 90 days to file, 45-day ruling, may withhold payment of the disputed amount, no credit-bureau report (LTOSF art. 23); provisional credit if reported within 48 h (secondary source [W]).
    - Argentina: BCRA, 10 business days [W].
- **Data:** complaints (`creation_date`, `status`, `subcategory`, `days_open`) and `customers.country`. Optionally `assignment_date` and `first_response_date`, which need one SQL column each.
- **Why it's new:** prior research proposed clocks for new disputes. This applies them to following up existing cases, adds a no-duplicate guard, and shares one rule table between the pipeline and the agent.
- **Effort:** 0.5 day.
- **Risks:** legal wording (label it "regla sintética"); C11 approximates business days.
- **Demonstrates:** P08 (main), P07.

### 3. Record-integrity annotator (deterministic check)
- **What it does:** an after-tool hook appends `data_conflicts: [{rule: "K02", fields, values}]` to tool results. The prompt's existing rule ("records don't match → offer a person") then covers the whole cohort, and the hand-off carries the conflicts.
- **Classes it checks:**
  - K01: customer not Active;
  - K02: Active card past its expiry date;
  - K03 / K04: null limit, or negative available credit;
  - K05: pending for more than 30 days;
  - K06 / K08: code mismatch, or no code (explain only);
  - K09: 'Mexico' spelling;
  - K11: no merchant;
  - K12 / K13: case status vs age;
  - K15: dates after as_of.
- **Why it's new:** these are runtime data contracts whose rule ids match the `curate.json` defect classes. By the C-rule invariants it should fire **zero** times on the 1,500 clean customers, which makes it a built-in test, and grading on the cohort becomes deterministic. It also ties the data-engineering work to the agent.
- **Effort:** 0.5 day.
- **Demo logins:**
  - K02 `CLI-0IHHK5P7SSWR`: card 1498 Active but expired 2023-01-01, approved charge 2026-05-19, plus a 'Mexico' spelling.
  - K04 `CLI-10T3UI3DKVK2`: card 8934, balance 755,352.65 over a 350,532.42 limit.
  - K05 `CLI-0WWGTFVI9JX8`.

### 4. Promise checker on the human's composer (UI mechanic, deterministic)
- **What it does:** a frontend check runs before "Laura" sends a message. It flags:
  - refund or outcome promises;
  - days or dates that disagree with the case clock (proposal 2);
  - full card numbers, CVV or OTP;
  - amounts not in the ledger.
- **Why it's new:** the same policy applies to the bot and the human. Agent-assist products (US Bank, Cresta [W]) suggest replies; they don't check the human against the bot's verified facts.
- **Effort:** 2–3 h.
- **Risk:** false flags; it only warns.

### 5. Prior-contact context + repeat-contact priority floor (tool + rule)
- **What it does:**
  - A new SQL section in `get_session_context` returns up to 5 contacts from the last 90 days, from call_center_interactions (date, channel, `contact_reason`, `was_resolved`, `requires_followup`, `was_escalated`) and satisfaction_surveys (`main_score`, `nps_category`).
  - Rule: an unresolved, follow-up-required contact in the last 30 days sets the hand-off priority to high, tagged REPEAT_CONTACT.
  - The desk gets a "Previous contacts" panel.
- **Grounding [V raw]:** 8.4% of customers active in the last 30 days (6,419 of 76,029) have such a contact in the last 90 days, and P08 and P09 do.
- **Why it's new:** cross-channel memory taken from the bank's own records rather than LLM long-term memory. Per finding F14, state facts and never infer causes. Never quote transcripts.
- **Effort:** 0.5 day, including a Lambda redeploy.

### 6. Roster-aware routing (deterministic tool)
- **What it does:** maps the hand-off reason to a specialty (Fraudes / Quejas y Reclamos / Soporte Técnico), then filters service_agents by language, shift and `agent_status = 'Active'`. If no Portuguese speaker is on shift, it routes to a Spanish speaker with the case rendered in Spanish and the Portuguese original kept. The desk shows the matched agent instead of the hard-coded "Laura Restrepo".
- **Data:** service_agents, a dimension table loaded whole per curate E2. A JSON snapshot avoids putting the hand-off Lambda in the VPC.
- **Why it's new:** prior research made the capacity argument (7 Portuguese fraud specialists, 0 at night) but built no router.
- **Effort:** 0.5 day.
- **Risk:** shift hours are an assumption.
- **Demonstrates:** P05.

### 7. Four-eyes checker sub-agent (multi-agent)
- **What it does:** after the goodbye, so it adds no latency, a second Strands Agent checks the summary against the ledger and the customer's own lines. It uses a different model family, no tools and no session manager. It labels each sentence `verified`, `customer_claim` or `unsupported`, and the desk strikes out the unsupported ones.
- **Why it's new:** maker-checker is a core banking control [W]. A second model family reduces errors that are correlated across models (the bench showed most models failing in the same ways).
- **Effort:** 0.5 day on top of proposal 1.
- **Stretch variant:** a desk copilot under a `role=desk_assist` claim that Cedar limits to read-only tools.

### 8. Wallet lockdown (tool + policy)
- **What it does:** for a lost wallet, one confirmed plan blocks credit **and debit** cards, listed by last 4 digits.
- **Change needed:** widen `block_credit_card` to `product_type IN (credit, debit)`. The `ll_write` role already has UPDATE on products [V].
- **Argentina:** the card must stay usable during a statement challenge (Ley 25.065), so only fraud or loss blocks are allowed there.
- **Effort:** 0.5 day.

### 9. No-LLM safe mode for the fraud journey (workflow)
- **Trigger:** two ConsentHook cancellations, a model error or throttle, a guardrail block, or a markup leak.
- **What it does:** code runs the journey itself with Strands interrupts and the ConfirmCard: recognise the charge? → block ••4497? → charge chips → claim → hand-off. All text comes from ES/PT templates.
- **Why it matters:** the model bench showed consent violations on most models, so degrading gracefully is a production-readiness story.
- **Effort:** about 1 day.

### 10. Dogwood rule: AI writes end at the hand-off (Cedar policy)
- **What it does:** a `forbid` on `block_credit_card` and `open_claim` when `formerly within 24h human_agent_hand_off::response`, plus `count` caps on blocks and claims per session. Temporal policies are available in us-east-1 [W].
- **Prerequisites:**
  - the `x-amzn-bedrock-agentcore-policy-session-id` header, set from the runtime session id in `gateway.py`, including on the bootstrap calls;
  - `GetWorkloadAccessToken` on the Gateway role;
  - workload-token propagation from the runtime (to be verified);
  - updating a policy returns 409 while sessions are open;
  - run it in LOG_ONLY first.
- **Note:** this is why the hand-off must stay a Gateway target.
- **Effort:** 0.5–1 day, risky. A stretch item.

### 11. Gateway RESPONSE-interceptor "data firewall" (platform check)
- **What it does:** one Lambda runs on every tool response. It:
  - drops deny-listed keys (`fraud_score`, `is_fraud`, `credit_score`, income…) even if a tool adds them;
  - fences untrusted text such as `merchant_name` and `description`;
  - attaches provenance;
  - hosts proposal 3's annotator in one place.
- **Facts [W]:** the order is REQUEST interceptor → Cedar → target → RESPONSE interceptor. That also answers design Q8: Cedar sees the rewritten request.
- **Effort:** about 1 day including CDK. Post-submission; proposal 3 is the agent-side version of the same logic.

### 12. Legal clock as a durable workflow (stretch)
- **What it does:** each claim or hand-off starts a Step Functions execution (or a Lambda durable function). It waits until the deadline minus N days, escalates if the case is still open, and sets `sla_breached` at the deadline. A "time-warp" factor speeds it up for the demo.
- **Effort:** 1–1.5 days.

**Dropped after checking the data:** a "do you recognise it?" evidence step modelled on Visa CE 3.0 (two or more earlier charges from the same merchant 120–365 days back). It fired **0%** on a 2,000-row sample, because the data has only 24 merchant names and about one transaction a month per customer [V].

### How the Yes/No confirmation should generalise
- Make it one "action contract" registry per write tool: confirmation, read-back template, the fields code sets, grounding (last 4 in the ledger, transaction ids from lookups), and a per-session cap.
- **Put `block_credit_card` behind the buttons too.** It is the most irreversible action and has the weakest control today.
- Have the hook write `customer_confirmed` after the click (false otherwise), the way CustomerIdHook writes `customer_id`. Cedar rule 3 then checks a value code set.
- After any successful write, clear `agent.state["session_context"]` so the next turn fetches it again.
- Later, record the click as a Gateway event hidden from the model, so a Dogwood `formerly within` rule can require it.

---

## 5. Cut or simplify before the demo

1. Hide `transaction_fraud_detection` from the model with `tool_filters`. Ideally hide both bootstrap tools too, which leaves 6 tools the model can see.
2. Fix the stale context after writes (about 1 h). Without it the P07 demo can contradict itself.
3. Decide on the resolution-estimate line: run one query on DSQL, and if it returns null, drop "usually ~N days" from the script. Don't demo `claim_type=dispute`, which has no fee records and hits the taxonomy bug.
4. Delete `mcp_registry.py` and its tests and config.
5. Fix the drift in design doc §4 and §7: it still says Claude Sonnet 4.5 and lists tool reads the SQL doesn't do. Don't link the stale FAST guides from the README.
6. Never show classify's "confidence"; call it priority.
7. Keep long-term memory and STM summarization off.
8. Add `transaction_type` to `list_card_transactions`, or filter Payments out of the REVIEW step.

---

## 6. Sources and files read

**Web**
- AgentCore Gateway interceptors: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html and https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-types.html
- Interceptor order (REQUEST before Cedar), June 2026 blog: https://aws.amazon.com/blogs/machine-learning/secure-ai-agents-with-policy-and-lambda-interceptors-in-amazon-bedrock-agentcore-gateway/
- Temporal (Dogwood) policies: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html
- Strands interrupts: https://strandsagents.com/docs/user-guide/concepts/interrupts/ and https://strandsagents.com/docs/user-guide/sdk/interrupts-multi-agent/
- LTOSF art. 23: https://leyes-mx.com/ley_para_la_transparencia_y_ordenamiento_de_los_servicios_financieros/23.htm
- CONDUSEF 48 h provisional credit (secondary source, El Imparcial, 2026-08-05): https://www.elimparcial.com/dinero/2026/08/05/condusef-establece-que-los-bancos-deben-devolver-el-dinero-de-un-cargo-no-reconocido-en-dos-dias-habiles-si-el-reclamo-se-hace-en-48-horas-aunque-existe-un-plazo-de-90-dias-para-solicitar-la-aclaracion/
- CONDUSEF UNE 30 business days: https://www.condusef.gob.mx/documentos/marco_legal/DispRegistrosAnte-CONDUSEF.pdf
- BCRA Com. "A" 8203, refund within 10 business days (search excerpt; whether it covers card fraud or only improper charges is unverified): https://www.bcra.gob.ar/archivos/Pdfs/comytexord/A8203.pdf
- SFC SmartSupervision: https://auren.com/co/blog/implementacion-de-smartsupervision/ and https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6298459
- Visa CE 3.0: https://usa.visa.com/content/dam/VCOM/regional/na/us/support-legal/documents/compelling-evidence-3.0-merchant-readiness-mar2023.pdf
- Ethoca Consumer Clarity: https://www.ethoca.com/digital-customer-experience
- Agent assist: https://www.zenml.io/llmops-database/real-time-ai-agent-assistance-in-contact-center-operations and https://cresta.com/guides/best-ai-agents
- Maker-checker: https://en.wikipedia.org/wiki/Maker-checker and https://arxiv.org/pdf/2608.11344

**Repo files**
- Docs: `docs/LEDGERLENS_PRODUCT_DESIGN.md`; `docs/superpowers/specs/2026-10-03-curate-stage-design.md`.
- Data: `data_load/personas.json`, `schema.sql`, `expected.json`, `curate_rules.py` (C11 table).
- Analysis: `datathon/docs/analysis/2026-09-26-…`, `2026-10-02-…` and `2026-10-03-curated-customers.md`. The eval on-hold doc was read from commit d15be78 on branch `docs/eval-on-hold`.
- Reports: `datathon/reports/LATAM bank AI agent use cases.md` and `Jev tiered bot handoff use cases.md`.
- Agent: `agent/ledgerlens/ledgerlens_agent.py`, and in `tools/`: `system_prompt.py` (v7), `consent_hook.py`, `confirmation_hook.py`, `customer_id_hook.py`, `session_context.py`, `gateway.py`, `guardrail.py`, `leaked_markup.py`, `conversation_memory.py`; plus `README.md`.
- Gateway: all 9 `gateway/tools/*/tool_spec.json`, every `queries/postgresql/*.sql`, the `human_agent_hand_off` and `open_claim` use cases, both `fraud_bands.py`, and `gateway/policies/policy.cedar`.
- Infra: `infra-cdk/lib/backend-construct.ts`, `infra-cdk/config.yaml`.
- Frontend: `frontend/src/lib/handoff.ts`, and in `components/chat/`: `AgentDesk.tsx`, `HandOffTicket.tsx`, `ChatInterface.tsx`.
