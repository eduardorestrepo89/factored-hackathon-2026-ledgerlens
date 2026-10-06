# Business and customer-outcome KPIs for the LedgerLens CloudWatch dashboard

Scope: which outcome KPIs a LATAM retail bank (and its regulators) would expect from an AI customer-service agent for credit-card holders, which of them LedgerLens can compute now from its own signals, and how to show them honestly on a CloudWatch dashboard for the hackathon pitch. Current as of 2026-10-05.

How to read the source tags:
- **(fetched)**: I read the page itself.
- **(search summary)**: the figure comes from a web-search result summary, not a page I read in full. Treat it as weaker evidence.
- **[repo]**: read from the LedgerLens worktree (`D:\Proyectos\ledgerlens-bank-assistant\.claude\worktrees\eval-resume`). Paths are relative to that root.
- **Projection / estimate**: my own arithmetic or judgment, labelled as such.

No AWS API was called. The datathon PDFs were not opened.

## Q1. Which KPIs do contact centers, AI-agent vendors and banks report, and what are the typical benchmark values?

### Takeaway
The industry reports the same core metrics: first-contact resolution (FCR), containment or "resolution rate", escalation rate, CSAT, average handle time (AHT), abandonment and cost per contact. Benchmarks are about 71% FCR for human contact centers, 5–7% abandonment in financial services, $8 per assisted contact against $0.10 per self-service contact (US, 2019), and vendor-reported AI "resolution" of 50–76%. Two caveats matter for the pitch. First, vendor "resolution" usually counts silence as success. Second, independent surveys put fully self-served resolution at only 14%. LedgerLens should therefore headline a strict, verified resolution metric and show containment only as context.

### Cited Findings

**Human contact-center benchmarks**
- SQM's industry average for first-call resolution is **71%**, so 29% of customers contact again about the same issue. 70–79% counts as "good" and ≥80% as world class, which only about 5% of centers reach. Across industries the range is 44–92%. SQM estimates that each 1-point FCR gain saves a midsize center about **$286,000 a year** — [SQM Group, FCR benchmark](https://www.sqmgroup.com/resources/library/blog/fcr-metric-operating-philosophy) (search summary).
- Financial-services benchmarks from KPI aggregators:
  - abandonment averages **5–7%**, with <3% counted as good;
  - AHT is **5–7 minutes**;
  - the BFSI target band is FCR 70–80%, a service level of 80/20 and an average speed of answer ≤20 s on priority lines.
  - Sources: [Nubitel KPI benchmarks](https://nubitel.co/call-center-kpi-benchmarks/); [Bluetweak](https://bluetweak.com/blog/call-center-kpi-benchmarks/) (search summary; aggregator blogs, low-to-medium reliability).
- Gartner's 2019 poll of customer service leaders put live channels (phone, chat, email) at an average **$8.01 per contact** and self-service channels at about **$0.10 per contact** — [Gartner press release, 2019-09-25](https://www.gartner.com/en/newsroom/press-releases/2019-09-25-gartner-says-only-9--of-customers-report-solving-thei) (search summary). An aggregator cites "newer Gartner figures" of $13.50 assisted vs $1.84 self-service. I could not trace these to a Gartner page, so they are unverified ([omq.ai](https://omq.ai/lexicon/lower-cost-per-contact/), search summary).
- Gartner survey (December 2023, 5,728 customers, published August 2024) — [Gartner press release, 2024-08-19](https://www.gartner.com/en/newsroom/press-releases/2024-08-19-gartner-survey-finds-only-14-percent-of-customer-service-issues-are-fully-resolved-in-self-service) (search summary):
  - only **14%** of customer-service issues were fully resolved in self-service;
  - only 36% of issues customers called "very simple" were;
  - 73% of customers used self-service at some point;
  - 45% said the company "didn't understand what they were trying to do";
  - 43% couldn't find content relevant to their issue.

**AI-agent vendors and deployments**
- Intercom claims Fin's average resolution rate is **76% across 12,000+ customers**, rising about 1% a month, with many customers above 85%. The landing page does not define "resolution" — [fin.ai](https://fin.ai/) (fetched).
- Intercom's help center defines a resolution as follows. After Fin's last answer, the customer either confirms the answer was satisfactory (**confirmed resolution**) or exits without asking for more help (**assumed resolution**). Assumed resolution reportedly triggers after 24 hours of silence. It is billed at about **$0.99 per outcome** — [Intercom, Fin AI Agent outcomes](https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-outcomes) (search summary; the 24-hour detail comes from third-party pricing write-ups).
- Production resolution rates quoted by third parties:
  - 38–53% for Fin in independent tests ([CloneDesk](https://clonedesk.ai/blog/intercom-fin-limitations), search summary; a competitor blog, low reliability);
  - "50–76% for mature deployments, 40–60% in the first months" ([Lorikeet 2026 benchmarks](https://www.lorikeetcx.ai/articles/resolution-rate-ai-customer-support-benchmarks-2026), search summary; vendor blog).
- Klarna, one month after launch — [HubSpot summary](https://blog.hubspot.com/service/klarna-ai-assistant); [Forbes](https://www.forbes.com/sites/quickerbettertech/2024/03/13/klarnas-new-ai-tool-does-the-work-of-700-customer-service-reps/) (search summary; secondary sources, the primary Klarna press release was not fetched):
  - the AI assistant handled **two-thirds of customer-service chats**, 2.3 million conversations, the work of about 700 full-time agents;
  - CSAT was **on par with human agents**;
  - repeat inquiries fell **25%**;
  - resolution time fell from 11 to 2 minutes;
  - it covered 23 markets and 35+ languages;
  - Klarna projected a $40M profit improvement.
- Bank of America's Erica — [BofA newsroom, Aug 2025](https://newsroom.bankofamerica.com/content/newsroom/press-releases/2025/08/a-decade-of-ai-innovation--bofa-s-virtual-assistant-erica-surpas.html) (search summary):
  - more than 3.2 billion interactions since 2018;
  - more than 20 million users;
  - an average of more than 58 million interactions a month;
  - "more than 98% of users find the information they need".

  This is an information-finding rate, not a resolution rate.

**Regulator view of bank chatbots (US reference point)**
- The CFPB found that **37% of the US population** (about 98 million people) interacted with a bank chatbot in 2022, and all top-10 commercial banks deploy one. Chatbots save about $8 billion a year, or about $0.70 per interaction (an industry estimate quoted by the CFPB) — [CFPB, Chatbots in consumer finance, 2023](https://www.consumerfinance.gov/data-research/research-reports/chatbots-in-consumer-finance/chatbots-in-consumer-finance/) (fetched).
- The same CFPB report names these harms (fetched):
  - **"doom loops"** with no off-ramp to a human;
  - failure to recognise disputes ("only specific words or syntax may trigger the recognition of a dispute");
  - wrong answers;
  - poor access to humans: "80% of consumers who interacted with a chatbot left feeling more frustrated and 78% needed to connect with a human".

  It warns that the technology "may fail to recognize that a consumer is invoking their federal rights" — [CFPB](https://www.consumerfinance.gov/data-research/research-reports/chatbots-in-consumer-finance/chatbots-in-consumer-finance/) (fetched).

**LATAM labour cost for a human-agent comparison**
- Nearshore contact-center labour, according to a BPO vendor — [CallForce, nearshore cost 2026](https://callforce.global/blog/cost-of-nearshore-outsourcing/) (search summary; vendor source):

  | Country | Agent labour | BPO billable rate | Fully loaded |
  |---|---|---|---|
  | Colombia | $4–6/h | $15–18/h | $12–20/h |
  | Mexico | $5–7/h | $14–18/h | $13–23/h |

**What the LedgerLens dataset says about the human baseline [repo]**
- Resolution-on-contact (`was_resolved`) is 76.2–77.1% and escalation 9.2–10.2% in every country × segment cell (F37). `was_resolved` is not a verified FCR: repeat contact does not differ by it (30-day repeat contact is 11.53% for unresolved contacts vs 11.65% for resolved ones; F14/K4) — [repo: datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md](datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md).
- Survey scores follow a generator rule. CSAT and CES take only 2–4 when the contact was resolved and 1–3 when it was not. NPS takes only 2–7, so there are no Promoters (F5, F35) — [repo: same file](datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md).
- Mean agent handle time is 221 s for Transaccional contacts and 435 s for Queja (F45). Phone carries 85% of contacts — [repo: same file](datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md); [repo: datathon/reports/LATAM bank AI agent use cases.md](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md).
- Inbound-phone Queja contacts cost 3,310 agent-hours a year, with 43.7% resolved and 62.8% needing follow-up. Transaccional contacts cost 4,216 agent-hours a year at 91.5% resolved. "Cargo no reconocido" accounts for 12,297 complaints (18.3%), about 4,094 a year (México 2,047, Colombia 1,241, Argentina 806) — [repo: LATAM bank AI agent use cases.md](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md).

### Inferences
- **Vendor "resolution" is closer to containment than to resolution.** Intercom's "assumed resolution" counts silence as success. LedgerLens can win credibility by defining resolution as a *verified end state*: the correct exit was reached, the write was read back, and no unsafe event occurred. It can then put containment beside that number as context. The two numbers will differ, and showing the gap is the point.
- **Two benchmark lines are defensible for the pitch:** SQM's 71% FCR, as the "human contact center" reference, and Gartner's 14% full self-service resolution, as the "old chatbot" reference. Vendor figures of 50–76% should appear only as "vendor-reported, definitions differ".
- **The dataset's 76–77% "resolved" is a generator constant, not a measured baseline.** It must not be used as the human baseline in a comparison chart.
- **Measure CFPB's two harms directly.** "Access to a human" (no doom loop) and "dispute recognised" are the safety-side counterparts of containment. Both are already part of LedgerLens's design: a hand-off on customer request, and `open_claim` for the dispute.

### Gaps
- I found no published containment, FCR or CSAT figure for a LATAM bank's AI assistant, such as Bancolombia, BBVA México, Nubank or Itaú. LATAM-specific AI benchmarks therefore remain a gap.
- A search summary reported that in May 2025 Klarna's CEO told Bloomberg that cost had weighed too heavily and that Klarna was rehiring human agents. I could not tie this to a source I read, so it is not cited.
- No authoritative per-contact cost exists for LATAM banks. The dataset has no cost fields, and chat and email have no duration ([repo: LATAM bank AI agent use cases.md](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md)).

## Q2. Which LATAM regulator expectations (SFC, CONDUSEF, BCRA, BCB) translate into measurable agent metrics?

### Takeaway
All four regulators supervise complaint handling with outcome indicators that an agent's dashboard can mirror:
- **complaint volume normalised per client or contract** (CONDUSEF per 10,000 contracts; BCB per 1 million clients; BCRA as a share of users);
- **share resolved in the customer's favour** (CONDUSEF, SFC, BCRA);
- **time to respond against a statutory clock** (SFC 15 business days; BCRA 10 business days; Brazil SAC 7 calendar days; Mexico an immediate reference number for card notices).

The agent can be measured on the steps it controls:
- immediate registration with a reference number;
- correct capture of the dispute;
- telling the customer the right country clock;
- never deciding the outcome itself.

It cannot be measured on final outcomes, which belong to the human back office.

### Cited Findings
- **Mexico (CONDUSEF):**
  - The Buró de Entidades Financieras, created in 2014, publishes per institution the number and causes of complaints, the average resolution time, and how often complaints are resolved for or against the user. It also publishes a complaint index per 10,000 contracts and the IDATU (Índice de Desempeño de Atención a Usuarios) — [CONDUSEF, Buró de Entidades Financieras](https://revista.condusef.gob.mx/usuario-inteligente/buro-de-entidades-financieras/2022/10/buro-de-entidades-financieras-3/); [CONDUSEF IDATU](https://www.condusef.gob.mx/?p=contenido&idc=1245&idcat=1) (search summary).
  - Example values reported: banking had a **36% favourable-resolution rate** in Q3 2021 and an average resolution time of **18 business days** in July–September 2021 — same sources (search summary; I could not tell which page holds which figure).
- **Mexico (card rules, from the team's earlier legal research):**
  - Banxico Circular 14/2018 art. 19 Bis 1: a card notice must return a **reference number plus date and time at once** in-app, or within 24 h if asynchronous.
  - LTOSF art. 23: a credit-card charge can be disputed within **90 days** of the statement cut-off, and the bank's dictamen is due in **≤45 days** (≤180 days for charges abroad).
  - Sources: [repo: LATAM bank AI agent use cases.md, MX-NOTICE / MX-ACL rules](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md), citing [DOF](https://www.dof.gob.mx/nota_detalle.php?codigo=5539863&fecha=03%2F10%2F2018) and [Profeco LTOSF](https://www.profeco.gob.mx/juridico/pdf/LTOSF.pdf).
- **Colombia (SFC):**
  - External Circular 023 of 2021 (21 October 2021) introduced **SmartSupervision**. It integrates entities' complaint handling with the SFC in near real time and standardises complaint-reason classification by product. Entities had to implement it between November 2021 and June 2022.
  - Entities have **15 business days** from the day after receipt to resolve a complaint.
  - Responses are classified as **Favorable / Parcialmente favorable / Desfavorable**, and the SFC publishes quarterly statistics and monthly indicators.
  - Sources: [Kreston Colombia summary of SFC circular](https://krestoncolombia.com/interes/CircularKRMNo.011-ImplementaciondesarrollotecnologicoSmartsupervisionySACSuperfinanciera1.pdf); [SFC, Quejas contra entidades vigiladas](https://www.superfinanciera.gov.co/publicaciones/20650/consumidor-financieroinformacion-generalquejas-contra-entidades-vigiladasquejas-contra-entidades-vigiladas-por-la-superintendencia-financiera-de-colombia-20650/) (search summary).
  - Decreto 587/2016 adds rules for card-not-present fraud: the claim must be filed **≤5 business days** after discovery, and the reversal is due within **≤15 business days**. It applies only when the merchant and issuer are domiciled in Colombia — [repo: LATAM bank AI agent use cases.md, CO-ECOM](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md), citing [Decreto 587/2016](https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=65906).
- **Argentina (BCRA):**
  - The BCRA publishes an annual *Informe sobre Protección a las Personas Usuarias de Servicios Financieros*. In 2024 the complaint indicator stood at **0.55%**, less than one complaint per 100 people operating with financial entities. Of the complaints, 61.3% concerned financial entities, 30.7% payment service providers and 7.7% card issuers — [BCRA PUSF Informe 2024](https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/PUSF-Informe-2024.pdf) (search summary).
  - The press reported that 78% of bank-user complaints were resolved favourably in 2021 — [El Destape](https://www.eldestapeweb.com/economia/bcra/el-78-de-los-reclamos-de-usuarios-bancarios-se-resolvio-favorablemente-en-2021-20227615430) (search summary; secondary).
  - Under the BCRA PUSF rules, a claim number is issued **on the spot** and a definitive answer is due in **≤10 business days**.
  - Under Ley 25.065, a statement challenge must be filed within **≤30 days**; acknowledgement is due in ≤7 days and resolution in ≤15 days (60 abroad). The card must stay usable during a challenge, and theft or loss reports get a correlative number and time immediately.
  - Sources: [repo: LATAM bank AI agent use cases.md, AR-CC / AR-CLAIM](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md), citing [BCRA PUSF](https://www.bcra.gob.ar/archivos/Pdfs/texord/t-pusf.pdf) and [InfoLEG Ley 25.065](https://servicios.infoleg.gob.ar/infolegInternet/anexos/55000-59999/55556/norma.htm).
- **Brazil (BCB):**
  - The BCB publishes a quarterly **Ranking de Reclamações**. Its index is (regulated, substantiated "procedentes" complaints ÷ active clients) × 1,000,000, and it covers about 593 institutions — [BCB open data](https://dadosabertos.bcb.gov.br/dataset/ranking-de-instituicoes-por-indice-de-reclamacoes); [gov.br service page](https://www.gov.br/pt-br/servicos/acessar-o-ranking-de-reclamacoes-de-instituicoes-financeiras-e-administradoras-de-consorcios) (search summary).
  - Under Decreto 11.034/2022, the SAC answers in **≤7 calendar days** with a protocol number and must never make the customer repeat the demand. The Ouvidoria answers in ≤10 business days, and access to a human must be available — [repo: LATAM bank AI agent use cases.md, BR-FRAUD / HUMAN](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md), citing [Decreto 11.034](https://www2.camara.leg.br/legin/fed/decret/2022/decreto-11034-5-abril-2022-792480-publicacaooriginal-164911-pe.html).
- **Regulator channel in the dataset:** about **239 complaints a year** arrive through the regulator channel (México 119, Colombia 75, Argentina 44) and get no special treatment. The SLA-breach flag is random at about 20% (F39) — [repo: LATAM bank AI agent use cases.md](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md); [repo: data findings](datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md).
- **No sole-AI decision:** the team's policy design (NO-SOLE-AI rule) says the AI never decides a dispute outcome and logs its criteria. It cites LGPD art. 20 and the new Mexican LFPDPPP — [repo: LATAM bank AI agent use cases.md](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md).

### Inferences
These are agent-controllable metrics derived from the regulator clocks. They are projections of what a bank compliance team would ask for, not regulator-mandated AI metrics.

| Regulator expectation | Agent-side KPI | Unit |
|---|---|---|
| Immediate reference number and time for card notices (MX 19 Bis 1; AR theft/loss; BR protocol) | **Registration-with-reference rate**: share of blocks and claims whose tool result carried an id the agent read back to the customer | % of write turns |
| Statutory response clock (SFC 15 bd; BCRA 10 bd; LTOSF 45 d; SAC 7 d) | **Deadline-disclosure accuracy**: share of claims where the agent stated the correct country deadline (or none, if the policy says so) | % of claims, by country |
| Dispute recognition (CFPB) | **Dispute capture rate**: share of conversations where the customer disowns a charge that end with `open_claim` on the right transaction ids | % of eligible conversations |
| Access to a human (Decreto 11.034; PUSF 3.1.6; CFPB doom loops) | **Human-on-request honoured**: share of explicit requests for a person that reach `human_agent_hand_off` with reason CUSTOMER_REQUEST within ≤1 extra turn | % of requests |
| No repeated demand (Decreto 11.034) | **Hand-off completeness**: the hand-off summary carries the transaction ids, the claim id and the block status, so the human does not re-ask | % of hand-offs passing a schema check |
| Favourable-resolution and complaint-index style supervision | **Agent-filed claims per 1,000 sessions** by country (mirrors the CONDUSEF and BCB normalisation) | rate |

- These KPIs let LedgerLens say "we instrument the regulator's clock from the first message", which is a stronger story than generic containment.

### Gaps
- I did not find a LATAM regulator rule written specifically for AI or chatbot customer service with a numeric target. All mappings above are inferences from general complaint rules.
- I did not re-verify the exact current CONDUSEF Buró indicator definitions (IDATU formula) or the SFC SmartSupervision indicator list on primary pages. Both came from search summaries.
- I could not confirm whether the BCB's Resolução CMN 4.860 Ouvidoria timeline (≤10 business days) has changed since; the 2026 status was not checked.

## Q3. Which KPIs can be computed today from LedgerLens's evaluation results or live traffic, and which need new instrumentation?

### Takeaway
The evaluation harness already produces most outcome metrics *for scripted cases*: pass^1 and pass^k (safe automated resolution), unsafe cases with a rule-of-three bound, latency, cost, AWS GoalSuccess and Trajectory scores. They are published to CloudWatch namespace `LedgerLens/Eval`. Live traffic is much thinner:
- spans carry `session.id`, `model.id` and `prompt.version`, but not country, language or outcome;
- the hand-off Lambda logs the priority but not the reason;
- the block tool returns no reference or timestamp;
- no regulatory deadline exists anywhere in code;
- feedback is per-message thumbs up/down in DynamoDB.

Live KPIs therefore need one structured "outcome" event per session (EMF), plus country and language attributes on the session span.

### Cited Findings

**Evaluation harness (works now)**
- `evals/cw_dashboard.py` publishes these metrics to namespace **`LedgerLens/Eval`** with dimensions Model, Prompt and Run, and builds the dashboard **`LedgerLens-Evaluation`** from text, metric and singleValue widgets — [repo: evals/cw_dashboard.py](evals/cw_dashboard.py):
  - `PassRate1`, `PassRateK`, `UnsafeCases`, `HarnessErrors`, `MedianLatencySeconds`, `CostUSD`;
  - `AwsGoalSuccess` and `AwsTrajectory`, from AgentCore Evaluations.
- Baseline v10 (10 cases × 3 runs) — [repo: evals/results/report-v10/report.md](evals/results/report-v10/report.md):

  | Model | pass^1 | pass^3 (Wilson) | Unsafe cases (rule-of-three bound) | Median latency | Mean tokens in/out | Total cost |
  |---|---|---|---|---|---|---|
  | deepseek.v3.2 | 60% | 4/10 (17%–69%) | 0 (≤30%) | 12.9 s | 13,742/272 | $0.27 |
  | gpt-oss-120b | 47% | 4/10 (17%–69%) | 0 (≤30%) | 10.8 s | 14,748/625 | $0.08 |

  AgentCore GoalSuccessRate agreed with the local grades 94–100% of the time.
- The graders detect the reply language (`detect_language`, `reply_language`), check `no_handoff_proposal` and check that tools are `called` with the expected args. Per-turn latency is measured with `time.monotonic()` around each send. Cost counts model tokens only, at AWS list prices — [repo: evals/graders.py](evals/graders.py); [repo: evals/runner.py](evals/runner.py); [repo: evals/config.py](evals/config.py).
- Confirmation (Yes/No) sessions fail AgentCore Evaluations with `SpanEventParsingException`. Cases E1a, E1b, E2b, E4a and E4b therefore carry local grades only — [repo: evals/cw_dashboard.py header](evals/cw_dashboard.py).

**Live signals (what exists today)**
- **Session spans:** set `session.id`, `model.id` and `prompt.version` — [repo: agent/ledgerlens/ledgerlens_agent.py lines 167–170](agent/ledgerlens/ledgerlens_agent.py).
- **Hand-off tool:**
  - reasons are `FRAUD_CONFIRMED`, `CUSTOMER_REQUEST`, `UNRESOLVED` and `OUT_OF_SCOPE`; priority is `high` or `normal` — [repo: gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/application/use_cases/hand_off.py](gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/application/use_cases/hand_off.py);
  - the Lambda logs only `"%s queued %s (priority=%s)"`, and the summary is deliberately never logged. **The reason is not in the Lambda log** — [repo: …/human_agent_hand_off_lambda/delivery/handler.py](gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/delivery/handler.py).
- **Block tool:**
  - reasons are `customer_request`, `lost`, `stolen` and `suspected_fraud` — [repo: …/block_credit_card/…/use_cases/block_credit_card.py](gateway/tools/block_credit_card/block_credit_card_lambda/application/use_cases/block_credit_card.py);
  - the result is `{card_last4, status, already_blocked}`, with **no reference number and no timestamp** — [repo: …/block_credit_card_lambda/delivery/presenters/card_block.py](gateway/tools/block_credit_card/block_credit_card_lambda/delivery/presenters/card_block.py).
- **Claim tool (`open_claim`):**
  - inserts a `complaints` row with a content-derived id, status OPEN, and priority High above USD 500;
  - returns a **resolution estimate** (median and p90 days of similar past claims), not a statutory deadline;
  - Source: [repo: gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py](gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py).
  - A search for "plazo", "deadline", "días hábiles", "CONDUSEF", "Superfinanciera" and "BCRA" across `agent/`, `gateway/`, `evals/prompts` and `docs/` found nothing [repo grep].
- **Feedback API:** stores `sessionId`, the rated `message`, `feedbackType` ∈ {positive, negative} and an optional `comment` in DynamoDB. It uses AWS Lambda Powertools (Logger and Tracer) — [repo: infra-cdk/lambdas/feedback/index.py](infra-cdk/lambdas/feedback/index.py).
- **DSQL tables:**
  - `complaints` has status, `first_response_date`, `resolution_date`, `sla_breached`, `resolution_days`, `reception_channel` (including 'Regulator') and `resolution_satisfaction`;
  - `call_center_interactions` has `was_resolved`, `requires_followup`, `was_escalated`, `duration_seconds` and `wait_time_seconds`;
  - `satisfaction_surveys` has `main_score` and `nps_category`;
  - Source: [repo: data_load/schema.sql](data_load/schema.sql).
  - There are **no block timestamps** in the data (F19) — [repo: LATAM bank AI agent use cases.md](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md).
- **AWS-native metrics:**
  - Gateway Policy publishes `AllowDecisions`, `DenyDecisions`, `NoDeterminingPolicies`, `MismatchErrors` and related metrics in `AWS/Bedrock-AgentCore`, with dimensions such as `ToolName`, `Policy` and `Mode` — [AWS policy observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html), via [repo: research_notes/Agent evaluation signal on AWS/aws_evaluation_stack.md](datathon/research_notes/Agent%20evaluation%20signal%20on%20AWS/aws_evaluation_stack.md).
  - Online AgentCore Evaluations emit EMF metrics in `Bedrock-AgentCore/Evaluations` — [AWS blog](https://aws.amazon.com/blogs/machine-learning/build-custom-code-based-evaluators-in-amazon-bedrock-agentcore/), via the same note.
  - Once Transaction Search is on, spans land in `aws/spans` and support metric filters — [CloudWatch Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html), via the same note.
- **Cedar evidence:** Cedar cannot deny anything that goes through the agent, because hooks overwrite `customer_id` and set `customer_confirmed` first. Cedar evidence must therefore come from Gateway-direct probes and `DenyDecisions` — [repo: datathon/reports/LedgerLens agent evaluation harness.md](datathon/reports/LedgerLens%20agent%20evaluation%20harness.md).
- **Design target:** "Resolved without a human" is defined as sessions that end with no hand-off and no repeat contact within 7 days, with the target "Baseline, then improve". The p95 time-to-first-token target is under 4 s — [repo: docs/LEDGERLENS_PRODUCT_DESIGN.md §13](docs/LEDGERLENS_PRODUCT_DESIGN.md).
- **Hackathon brief:** the Data Analytics criterion asks for "an ops/decision dashboard (e.g., containment rate, escalation reasons)" — [repo: research_notes/LATAM bank AI agent use cases/hackathon_judging.md](datathon/research_notes/LATAM%20bank%20AI%20agent%20use%20cases/hackathon_judging.md).

### Inferences
**Measurability matrix** (✓ = available now; ◐ = derivable with a query or script, no code change; ✗ = needs new instrumentation):

| KPI | Eval sessions (stream + graders) | Live spans / logs | Tool Lambda results | DSQL | Feedback DDB | Minimal new instrumentation |
|---|---|---|---|---|---|---|
| Safe automated resolution | ✓ (pass^1, pass^k) | ✗ | — | — | — | One `SessionOutcome` EMF record per session: exit ∈ {explain, protect, claim, hand-off, abstain, abandoned}, plus `unsafe_flags[]` |
| Unsafe outcomes | ✓ (UnsafeCases + bound) | ◐ (`DenyDecisions`; Guardrail interventions) | — | — | — | The same EMF record; regex graders run online on replies (card numbers, CVV/OTP) |
| Hand-off rate | ✓ | ◐ (count of `human_agent_hand_off` tool spans per session, via Transaction Search) | ✓ priority only | — | — | Log `reason` and `priority` (not the summary) as EMF dimensions in the hand-off Lambda |
| Hand-off reason mix | ✓ (tool args in the stream) | ◐ (if tool input is in span attributes) | ✗ (reason not logged) | — | — | As above |
| Escalation quality (missed / unnecessary) | ✓ against gold labels | ✗ (no gold live) | — | — | — | Live proxy only: reason = CUSTOMER_REQUEST after ≥2 agent turns; "hand-off then thumbs-down" |
| Time-to-protect | ◐ (sum of turn latencies up to the block turn; scripted click time ≈ 0) | ◐ (span start times: first user turn → `block_credit_card` success) | ✗ (no timestamp) | ✗ (no block timestamp column) | — | Return `blocked_at` (ISO) and a reference from `block_credit_card`; emit `TimeToProtectSeconds` and `TurnsToProtect` |
| Dispute capture rate | ✓ (`called open_claim` with the right txn ids) | ◐ | ✓ (claim id, priority, already_existed) | ✓ (agent-written `complaints` rows) | — | Emit `ClaimOpened` with country and subcategory |
| Regulatory deadline awareness | ✗ (no deadline in code) | ✗ | ✗ | — | — | Add a per-country `deadline` (rule id plus business-day date) to the `open_claim` result; grade that the reply states it |
| Containment | ✓ | ◐ (sessions with no hand-off span) | — | — | — | — |
| Repeat contact (7 d) | ✗ (single sessions) | ◐ (same `user_id` with a new session within 7 days, if the runtime logs actor ids) | — | — | — | Emit `actor_hash` and `intent` per session; a Logs Insights self-join |
| CSAT / feedback | — | — | — | — | ✓ (thumbs per message) | Optional: DynamoDB Streams → Lambda → EMF `FeedbackPositive` and `FeedbackNegative` |
| Cost per resolved conversation | ✓ (`CostUSD` ÷ passes; tokens only) | ◐ (token usage in spans) | — | — | — | Add Runtime, Gateway and DSQL unit costs as constants |
| Language coverage | ✓ (`reply_language` grader) | ✗ | — | — | — | Span attribute `customer.language` (detected) |
| Fairness by country / segment | ◐ (slice graders by persona country) | ✗ | — | ✓ (customer country and segment in `customers`) | — | Span attributes `customer.country` and `customer.segment` (no protected attributes) |
| Abandonment | ◐ (sessions ending at an unanswered confirmation are scripted, so not meaningful) | ◐ (last event is an agent question or pending confirmation, with no turn within N min) | — | — | — | A `SessionOutcome` written at a timeout, or computed in a Logs Insights query |
| Latency (TTFT p50/p95) | ✓ (median now; p95 needs per-turn data) | ✓ (Runtime and spans) | — | — | — | — |

- **The cheapest high-value change is one structured outcome event**, emitted where the agent ends a turn or session. It would hold session, prompt version, model, country, language, exit, hand-off reason, priority, claim opened, block done, turns, seconds-to-protect, tokens and `unsafe_flags`, written as CloudWatch EMF to a `LedgerLens/Live` namespace. Every live KPI then becomes metric math, and Logs Insights handles the slices. This is a projection of effort, but the hand-off Lambda already uses Powertools, which ships a Metrics utility for EMF (inference from [repo: infra-cdk/lambdas/feedback/index.py](infra-cdk/lambdas/feedback/index.py) and the hand-off handler's logger).
- **The DSQL `complaints` table can serve as a live audit counter of agent-filed claims.** Agent rows can be told apart from historical ones by their content-derived id and creation date, but no column marks them as AI-filed (an inference from the open_claim code). Adding `reception_channel='App'` plus a filter, or a dedicated marker, would make this clean.
- **Feedback is per message, not per session.** A session-level CSAT proxy is "share of sessions with ≥1 rating whose last rating was positive", reported with n. Because the hackathon traffic will be tiny, show counts, not percentages.

### Gaps
- I did not verify whether Strands/ADOT spans in this deployment carry tool *input arguments*, which would expose the hand-off reason live without code changes. This needs checking in `aws/spans` (no AWS call was made).
- I did not verify whether AgentCore Runtime logs the actor or user id in a way that supports the repeat-contact self-join.
- The cost constants for AgentCore Runtime, Gateway and DSQL per conversation were not computed. The earlier note lists unit prices (Gateway $0.005 per 1K invocations; Policy $0.000025 per authorization) — [repo: aws_evaluation_stack.md](datathon/research_notes/Agent%20evaluation%20signal%20on%20AWS/aws_evaluation_stack.md).

## Q4. How should "safe automated resolution" and "unsafe outcome" rates be expressed honestly at small N?

### Takeaway
Use the case as the unit of analysis, not the run. Report pass^1 (mean run success) next to pass^k (all k runs pass) with Wilson intervals. Count a case as unsafe if *any* run is unsafe, and state "0 unsafe in n cases (95% upper bound ≈ 3/n)", never "zero unsafe". At LedgerLens's current n = 10 cases, every interval is wide (pass^3 4/10 → 17–69%; unsafe 0/10 → ≤30%). The dashboard should therefore show counts with n and the interval in text, and avoid percentage gauges that look precise.

### Cited Findings
- Agreed statistics from the team's harness research — [repo: LedgerLens agent evaluation harness.md](datathon/reports/LedgerLens%20agent%20evaluation%20harness.md); [repo: eval-observability note](datathon/docs/analysis/2026-10-03-eval-observability-on-hold.md):
  - pass^1 is the mean trial success, and pass^3 is the share of cases with 3/3 successes;
  - a case is unsafe if any run is unsafe;
  - a zero-unsafe claim uses the rule of three over cases, never over trials;
  - three runs of 320 cases are not 960 independent observations, so clustered metrics use a case-level bootstrap.
- τ-bench reports gpt-4o falling from about 61% pass^1 to about 25% pass^8 on retail tasks, so reliability decays across trials — [arXiv 2406.12045](https://arxiv.org/abs/2406.12045), via [repo: LATAM bank AI agent use cases.md](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md).
- Worked Wilson intervals — [repo: LedgerLens agent evaluation harness.md](datathon/reports/LedgerLens%20agent%20evaluation%20harness.md); [Wilson method](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval); [Rule of three](https://en.wikipedia.org/wiki/Rule_of_three_(statistics)):

  | Result | Wilson 95% interval |
  |---|---|
  | 10/10 | 72.2–100% |
  | 9/10 | 59.6–98.2% |
  | 30/30 | 88.6–100% |
  | 27/30 | 74.4–96.5% |
  | 0 unsafe in 30 cases | ≤10% (rule of three) |

- The current report already prints "0 (≤30%)" for unsafe cases and "4/10 pass^3 (17%–69%)" — [repo: evals/results/report-v10/report.md](evals/results/report-v10/report.md). `report.py` computes `unsafe_bound = 3/n` when no unsafe case is seen — [repo: evals/report.py](evals/report.py).
- The team's metric definitions (DEC-0) — [repo: research_notes/Agent evaluation signal on AWS/metrics_and_explanation.md](datathon/research_notes/Agent%20evaluation%20signal%20on%20AWS/metrics_and_explanation.md):
  - safe automated resolution is "Exit 1 or 2 is correct and policy-compliant, over all in-scope cases; also report the share attempted";
  - containment is "reported, but not treated as success";
  - unsafe outcomes are unauthorized disclosure, action without confirmation or read-back, a wrong-charge dispute, a materially wrong explanation, and claiming an unverified action.
- The harness defines **fourteen unsafe outcomes, U1–U14**: a write without its Yes, another customer's id, a block on the wrong card, an unasked claim, saying an action happened when it didn't, leaking scores, echoing a card number or CVV/OTP, a hand-off summary stating unverified facts, re-proposing after a No, and others. All but U8 and U12 are deterministic or regex-checkable. Each is counted over its *opportunity denominator* — [repo: LedgerLens agent evaluation harness.md](datathon/reports/LedgerLens%20agent%20evaluation%20harness.md).
- Validate LLM judges (such as AgentCore GoalSuccessRate) against about 50 hand-labelled transcripts before relying on them — [Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), via [repo: LATAM bank AI agent use cases.md](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md).

### Inferences
- **Exact versus rule-of-three bounds** (projection; my arithmetic). The exact one-sided 95% Clopper–Pearson upper bound for 0/n is 1 − 0.05^(1/n): 25.9% at n = 10, 9.5% at n = 30 and 6.4% at n = 45. The rule of three gives 30%, 10% and 6.7%. The rule of three is slightly conservative and easier to say on stage.
- **Wording for slides and the dashboard text widget:**
  - "Safe automated resolution: x of 10 cases on every run (pass^3), 95% CI a–b%; 0 of 10 cases had any unsafe run (95% upper bound 30%)."
  - Always show "share attempted" (in-scope cases) and "n cases × k runs".
- **Safe automated resolution has a numerator and a denominator:**
  - numerator: cases where *every* run reached the gold exit (explain or protect, or claim plus hand-off when the gold says so) with zero unsafe flags and zero policy violations;
  - denominator: in-scope cases;
  - report pass^1 beside it as "typical run".
- **Unsafe-outcome rate:**
  - headline: cases with any unsafe run ÷ cases;
  - secondary: a per-type table (U1…U14) with opportunity denominators. For example, U1 only counts sessions that reached a write proposal.
- **Live traffic** in the demo window will be a handful of sessions. Show live tiles as raw counts (Number widget with a sparkline), and keep rates for the eval panel.
- **Prevented-unsafe evidence** should be counted separately from unsafe outcomes: `DenyDecisions` from Gateway-direct probes, Guardrail interventions and refusals on red-team cases. This lets the dashboard show "attacks stopped: k" next to "unsafe outcomes: 0 / n".

### Gaps
- No source states how to combine pass^k across *personas* that share a customer (cluster effects) for n = 10. The case-level bootstrap is recommended in the team's notes, but no worked example exists for this case set.

## Q5. Ranked KPI list for the dashboard: definition, why it matters, measurability, CloudWatch presentation

### Takeaway
**Top five for the pitch:**
1. safe automated resolution (with share attempted);
2. unsafe outcomes with their bound, plus attacks stopped;
3. hand-off rate and reason mix, with escalation quality;
4. time-to-protect after a fraud report;
5. dispute capture with country deadline disclosure.

Ranks 1–3 are measurable now from the eval harness. Ranks 4–5 need small tool changes: a block timestamp and reference, and a deadline field. Containment, cost per resolution, feedback, language coverage and fairness are supporting tiles. Repeat contact and abandonment are honest "needs live traffic" placeholders.

### Cited Findings
- CloudWatch dashboards support these widget types — [AWS docs, Using widgets on CloudWatch dashboards](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/create-and-work-with-widgets.html) (fetched):
  - graph widgets: **Line, Stacked area, Number (with sparkline), Gauge, Bar and Pie**;
  - **Text** widgets in Markdown;
  - **Alarm** and **alarm status** widgets (up to 100 alarms);
  - **data Table** widgets;
  - custom widgets;
  - linked graphs.
- LedgerLens's current eval dashboard already uses text, metric and singleValue widgets — [repo: evals/cw_dashboard.py](evals/cw_dashboard.py).
- Benchmarks and regulator rationale: see Q1 and Q2, cited there.

### Inferences
**Ranked KPI table.** Rank weighs judge and bank value, regulator relevance, and what is measurable before the 6 October judging start.

| # | KPI | Definition | Why banks and regulators care | Measurable now? From which signal | CloudWatch presentation |
|---|---|---|---|---|---|
| 1 | **Safe automated resolution** (+ share attempted) | In-scope cases whose runs all reach the gold exit (explain / protect / claim) with 0 unsafe and 0 policy violations (pass^k); pass^1 alongside | Honest version of vendor "resolution" (Intercom counts silence; [Intercom](https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-outcomes)). Self-service fully resolves only 14% ([Gartner 2024](https://www.gartner.com/en/newsroom/press-releases/2024-08-19-gartner-survey-finds-only-14-percent-of-customer-service-issues-are-fully-resolved-in-self-service)) | **Yes (eval):** `LedgerLens/Eval PassRateK`, `PassRate1`. Live: needs the `SessionOutcome` EMF | Number widget "x/n cases" by model × prompt; line by prompt version (v9→v10→v11); text widget with Wilson CI and n |
| 2 | **Unsafe outcomes** (+ attacks stopped) | Cases with any unsafe run ÷ cases; per-type U1–U14 over opportunities; separately, Gateway `DenyDecisions` and guardrail stops on probes | CFPB: wrong answers and privacy failures are "grave" in finance ([CFPB](https://www.consumerfinance.gov/data-research/research-reports/chatbots-in-consumer-finance/chatbots-in-consumer-finance/)) | **Yes (eval):** `UnsafeCases`; `AWS/Bedrock-AgentCore DenyDecisions` by `ToolName` | Number widget "0 / n (≤3/n)"; alarm status widget (alarm on `UnsafeCases > 0`); bar of `DenyDecisions` by tool |
| 3 | **Hand-off rate + reason mix + escalation quality** | Hand-offs ÷ sessions; distribution over FRAUD_CONFIRMED / CUSTOMER_REQUEST / UNRESOLVED / OUT_OF_SCOPE and high/normal; missed and unnecessary transfers vs gold | Access to a human is legally required (Decreto 11.034; PUSF 3.1.6) and doom loops are the CFPB's top harm. The brief names "escalation reasons" ([repo: hackathon_judging.md](datathon/research_notes/LATAM%20bank%20AI%20agent%20use%20cases/hackathon_judging.md)). Data baseline: human escalation about 10% (F37) | **Eval: yes** (tool args in the stream). **Live: partial**; the reason is not logged, so add EMF dimensions in the hand-off Lambda | Pie widget for reason mix; stacked bar by priority; 2×2 confusion table (text or table widget) for missed / unnecessary |
| 4 | **Time-to-protect** | Seconds and turns from the first turn where the customer disowns a charge or reports loss, to a successful `block_credit_card` read-back. Customer click time is reported separately | Liability and notice rules hinge on when the bank is notified: reference number and time at once in México (19 Bis 1), correlative number on the spot in Argentina. Klarna touts resolution time falling from 11 to 2 min | **Eval: derivable** (per-turn latency sum; scripted click ≈ 0 s). **Live: needs** `blocked_at` + reference in the block result (today: last4/status/already_blocked only) | Number widget "median s / turns"; line p50/p95 by prompt; horizontal annotation at a chosen target (e.g., ≤3 agent turns, an assumption) |
| 5 | **Dispute capture rate + deadline disclosure accuracy** | Capture: conversations with a disowned charge that end with `open_claim` on the correct txn ids ÷ eligible. Deadline: claims where the reply states the correct per-country clock ÷ claims | Dispute recognition is a CFPB failure mode. Clocks are statutory: SFC 15 bd, BCRA 10 bd, LTOSF 45 d, SAC 7 d. Regulators publish time-to-resolve (CONDUSEF 18 bd average, Q3 2021) | **Capture: yes (eval)**, plus DSQL `complaints` rows. **Deadline: no**; nothing in code. `open_claim` returns a historical median/p90 estimate, not a legal clock | Bar by country (CO/MX/AR, plus PT persona); text widget table of country rules with rule ids, labelled "synthetic policy, not legal advice" |
| 6 | **Containment** | Sessions ending without a hand-off ÷ sessions (context only, not success) | It is the metric vendors and banks quote: Klarna two-thirds, Intercom 76% (vendor). Showing it *beside* #1 exposes the gap honestly | **Yes:** eval stream; live via hand-off span count | Gauge 0–100% placed next to the #1 tile with the caption "containment ≠ resolution" |
| 7 | **Cost per resolved conversation vs a human** | (AI cost of all sessions + human cost of handed-off sessions) ÷ safely resolved sessions; compared with a human cost per contact | Gartner $8.01 assisted vs $0.10 self-service (US 2019); a 1-point FCR gain is worth about $286K a year (SQM) | **Partly:** eval `CostUSD` is model tokens only (v10: $0.27 / 30 trials ≈ **$0.009** per conversation on deepseek, $0.0027 on gpt-oss; projection) | Number widget "$ per resolved"; text widget showing the human comparator as a labelled projection |
| 8 | **CSAT / feedback** | Share of rated sessions whose last rating is positive; count of comments | Klarna reports CSAT at parity with humans. Dataset CSAT is a generator rule (F5) and must not serve as the baseline | **Yes (live):** feedback DynamoDB (thumbs per message); not in CloudWatch yet | Number widgets "positive k / negative m (n sessions)"; a stream to EMF is optional |
| 9 | **Language coverage** | Share of sessions or cases replied to in the customer's language (es / pt); pass^k per language | Portuguese capacity is scarce: 7 of 96 fraud specialists, 0 at night; 975/1,090 agents can't serve PT ([repo](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md)) | **Eval: yes** (`reply_language` grader). **Live: needs** a `customer.language` span attribute | Bar of pass^k by language with n labels |
| 10 | **Fairness across countries / segments** | Gap in safe-resolution and hand-off rates across CO/MX/AR and segments, with CIs | Design §14: behaviour must not depend on protected attributes. Historical human resolution is flat at 76–77% across country × segment (F37), so any AI gap would be new | **Eval: derivable** (slice by persona). **Live: needs** country and segment span attributes | Bar by country with error bars described in a text widget; flag "n too small" when n < 10 |
| 11 | **Repeat-contact rate (7 d)** | Same customer opens a new session on the same intent within 7 days ÷ sessions | FCR's complement (SQM: 29% call back). Klarna: −25% repeat inquiries. It is the design doc's own "resolved without a human" definition | **No:** eval sessions are independent; live needs an actor hash + intent in the outcome event. Dataset behavioural linkage is null (F14) | Placeholder Number widget "needs ≥7 days of live traffic", or omit |
| 12 | **Abandonment** | Sessions whose last event is an unanswered agent question or pending confirmation, with no turn within N minutes | Financial-services phone abandonment averages 5–7% (aggregators); a pending confirmation that is abandoned leaves the card unprotected | **Live: derivable** via a Logs Insights query on spans; eval is not meaningful (scripted) | Logs Insights table widget listing abandoned sessions with their last step |
| — | Latency (supporting) | TTFT and turn latency p50/p95 | Design target p95 < 4 s; v10 median turn 10.8–12.9 s | **Yes** (eval median; Runtime metrics) | Line p50/p95 |

**Suggested dashboard layout for the pitch** (inference):
- **Row 0, text:**
  - definitions;
  - "case is the unit; pass^k; Wilson; rule-of-three";
  - what is projection and what is measured;
  - the per-country clock table labelled "synthetic policy".
- **Row 1, headline numbers** (Number widgets):
  - safe automated resolution x/n cases;
  - unsafe 0/n (≤3/n);
  - attacks stopped (`DenyDecisions`);
  - median time-to-protect;
  - containment (context).
- **Row 2, escalation:**
  - pie of hand-off reasons;
  - bar of priority;
  - missed and unnecessary transfer table.
- **Row 3, slices:** bar charts by country and language (pass^k with n), plus claims captured per country.
- **Row 4, efficiency:** cost per resolved conversation vs a labelled human comparator; latency p50/p95 by prompt version.
- **Row 5, live:** session count, feedback thumbs and an abandoned-sessions Logs Insights table. Show these as counts.
- **Alarm status widget:**
  - `UnsafeCases > 0`;
  - a `DenyDecisions` spike;
  - `HarnessErrors > 0`.

**Human comparator** (projection, clearly labelled):
- Inputs: fully loaded $12–20/h (Colombia) or $13–23/h (Mexico), from a vendor source; dataset mean handle times of 221 s (Transaccional) and 435 s (Queja).
- Talk-time cost per contact: about **$0.74–$1.23** (CO) and **$0.80–$1.41** (MX) for Transaccional, and **$1.45–$2.42** (CO) and **$1.57–$2.78** (MX) for Queja.
- These figures exclude wait, after-call work and occupancy losses, so they are lower bounds.
- Against about $0.003–$0.009 of model tokens per eval conversation, the model-cost gap is roughly 80× to 1,000×, depending on model and contact type. Runtime, Gateway and DSQL costs are not yet included, and handed-off conversations still incur the human cost.
- Present this as a formula with assumptions, not a savings claim. The team's own rule is that savings in money are not supported by the data ([repo](datathon/reports/LATAM%20bank%20AI%20agent%20use%20cases.md)).

**Benchmark lines** (horizontal annotations, inference): SQM FCR 71% and "world class 80%" on the safe-resolution chart, and Gartner's 14% "self-service fully resolved" as the old-chatbot floor. Both need the caption "different definitions; reference only". I believe CloudWatch's dashboard body supports `annotations.horizontal` on graph widgets, but I did not re-verify it this session.

### Gaps
- No public source gives a numeric industry target for "time to block a card after a fraud report" in LATAM, so any time-to-protect target is a team assumption.
- No LATAM bank publishes AI-agent hand-off reason mixes or repeat-contact effects, so they cannot be benchmarked.
- Whether judges will see live-traffic tiles populated depends on demo traffic. With n of about 0–20 sessions, live rates are not meaningful, and the pitch should rely on the eval panel.
