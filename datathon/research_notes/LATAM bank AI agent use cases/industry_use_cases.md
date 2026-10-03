# Industry AI-agent use cases in retail-banking customer service (LATAM focus, 2024–2026)

Notes compiled 2026-09-29. Scope: customer-facing service agents at banks and fintechs that take actions, not only answer questions. Labels used: **[bank-reported]** means a bank press release, earnings release or executive quoted in the press. **[vendor claim]** means a technology vendor's case study or blog. **[secondary]** means an aggregator or blog summary where I could not open the primary source. Anything dated before 2024 is marked **(background)**.

---

## Q1. Which agentic (action-taking) customer-service use cases are banks deploying in 2025–2026, and how do they work (understand → decide → act → verify → escalate)?

### Takeaway
Across 2025–2026, deployments moved from answering FAQs to agents that take actions: card controls, conversational Pix and transfers, debt renegotiation on WhatsApp, scam interrogation before a payment, dispute and fraud intake, and copilots that write summaries for human agents. The best-documented results cluster in three areas:
- **Tier-1 containment:** Bradesco 82%, Nubank >60% "at or above human parity", Nequi 80%.
- **Collections on WhatsApp:** Banco do Brasil, +306% conversions and 50% handled with no human.
- **Pre-payment scam intervention:** Starling, +300% cancellations of suspicious payments. CBA, −76% scam losses from a wider set of tools.

The weakest evidence is for AI-mediated translation, retention/cancellation agents and fully autonomous dispute resolution.

### Cited Findings

**Pattern A — Tier-1 service agent with account context (answer and act on simple intents)**
- Bradesco (BR), BIA with generative AI:
  - 82% of initial service requests resolved by generative AI. More than 10M customers use the AI chat. About 450 AI use cases. Capabilities include Pix transfers and product information. Guardrails limit BIA's scope. Source: Patricia Kessler, Oct 28, 2025. [bank-reported] — [Bloomberg Línea](https://www.bloomberglinea.com.br/negocios/ia-generativa-resolve-82-dos-atendimentos-iniciais-no-bradesco-diz-diretora/)
  - Earlier figures, June 2025: 3M customers served by genAI BIA; the first chat layer is AI with 85–90% retention of demands; satisfaction 4.1–4.2 out of 5. — [TI Inside](https://tiinside.com.br/11/06/2025/com-ia-generativa-bia-ja-retem-ate-90-das-demandas-no-atendimento-digital-do-bradesco/); [Mobile Time](https://www.mobiletime.com.br/noticias/11/06/2025/bia-bradesco-ia-3-mi/)
- Nubank (BR/MX/CO):
  - "AI agents handle more than 60% of customer support conversations in Brazil at or above human parity" (Q2 2026 results). [bank-reported] — [Nu Holdings Q2 2026](https://nu.com/en/newsroom/company/nu-holdings-ltd-reports-second-quarter-2026-financial-results)
  - Earlier OpenAI customer story: the GPT-4o assistant resolves 55% of Tier-1 inquiries, handles more than 2M chats a month and cut chat response time by 70%. A call-center copilot gives agents summaries and recommended answers. [vendor claim, OpenAI] — [The Paypers summarizing OpenAI](https://thepaypers.com/fintech/news/nubank-partners-with-openai-in-order-to-elevate-customer-experience); [OpenAI](https://openai.com/index/nubank/) (page returned 403; figures taken from search summaries)
  - The assistant reportedly handles "up to 5 automated interactions before escalating". [secondary] — [Twig blog](https://www.twig.so/blog/ai-agents-in-fintech)
- Nequi (CO, Bancolombia group): 80% of customer-service interactions handled by AI; 98% response coverage; users can escalate to a human "without additional barriers"; about 28M users. Aug 6, 2026. [bank-reported] — [El Colombiano](https://www.elcolombiano.com/tecnologia/nequi-inteligencia-artificial-credito-atencion-cliente-machine-learning-colombia-NF39695697)
- Klarna, the global reference:
  - Feb 2024: 2.3M chats in the first month, equal to about 700 agents. [vendor/bank] — [OpenAI](https://openai.com/index/klarna/); [CX Dive](https://www.customerexperiencedive.com/news/klarna-reinvests-human-talent-customer-service-AI-chatbot/747586/)
  - Q3 2025: work equal to 853 FTEs, US$60M savings, CSAT "on-par" with humans. — [CX Dive](https://www.customerexperiencedive.com/news/klarna-says-ai-agent-work-853-employees/805987/)
- Monzo (UK), Ops Agent:
  - Grew from Q&A into end-to-end processes across 150+ intents, including Pot management, card replacement, fraud reporting and fraud investigations.
  - Giving the agent intent-gated access to customer context raised resolution of transaction-related queries by 10 percentage points.
  - Safety design: input/output guardrails, escalation when confidence drops, a "golden set" of 100 expert-approved conversations, and QA sampling that started at 100% and was reduced over time.
  - Source: [Conversational AI News](https://www.conversationalainews.com/how-monzo-bank-built-their-own-ai-agent-for-live-customer-support-without-losing-control/)
- Loop in this pattern:
  - Understand: intent classification plus customer context.
  - Decide: a policy/process runbook (Monzo writes these in Markdown).
  - Act: tool call.
  - Verify: guardrails and evaluation sets.
  - Escalate: on low confidence or after N turns (Nubank's ~5).

**Pattern B — Transaction/charge explanation ("why was I charged X?")**
- Mercado Pago (BR): "Half our use cases relate to help requests, understanding why interest rates are X or why account charges are Y." Daniel Holanda, AI Director, Feb 2026. — [Mobile Time](https://www.mobiletime.com.br/noticias/13/02/2026/mercado-pago-agente-ia/)
- Monzo: the +10 pp resolution gain came specifically on transaction-related queries once the agent could see customer context. — [Conversational AI News](https://www.conversationalainews.com/how-monzo-bank-built-their-own-ai-agent-for-live-customer-support-without-losing-control/)
- Wells Fargo Fargo: handles "providing transaction details, and answering questions about account activity"; 245.4M interactions in 2024. — [VentureBeat](https://venturebeat.com/ai/wells-fargos-ai-assistant-just-crossed-245-million-interactions-with-zero-humans-in-the-loop-and-zero-pii-to-the-llm)

**Pattern C — Card controls (block, unblock, freeze, replacement)**
- Bancolombia Tabot on WhatsApp and web: block/unblock cards and passwords, request tax certificates and statements, report suspicious messages. — [Bancolombia](https://www.bancolombia.com/acerca-de/sala-prensa/noticias/productos-servicios/como-reconocer-tabot-oficial)
- Revolut AIR, rolled out Apr 9, 2026 to 13M UK customers: covers card freezing, subscription management, spending analysis and travel support. — [FinTech Weekly](https://www.fintechweekly.com/news/revolut-air-ai-assistant-uk-customers-launch-2026)
- Monzo: card replacement is one of its phase-3 tool-calling actions. — [Conversational AI News](https://www.conversationalainews.com/how-monzo-bank-built-their-own-ai-agent-for-live-customer-support-without-losing-control/)

**Pattern D — Conversational money movement (Pix or transfers by text, voice or image)**
- Nubank:
  - Pix by audio, text or image, in the app and on WhatsApp. About 2M customers tested it on WhatsApp from Oct 2024; expanded Dec 10, 2024.
  - WhatsApp caps during testing: R$200 per transaction and R$2,000 per day. The same "Smart Defenses" fraud checks apply as in the app. Transaction time cut by up to 60%.
  - Source: [Nu newsroom](https://nu.com/en/newsroom/consumers/nubank-leverages-ai-to-scale-pix-operations)
  - A secondary summary reports an agentic transfer flow cut the process from 70 seconds over nine screens to under 30 seconds, with >90% accuracy and <0.5% error. [secondary] — [ZenML LLMOps DB](https://www.zenml.io/llmops-database/building-an-ai-private-banker-with-agentic-systems-for-customer-service-and-financial-operations)
- Banco do Brasil, conversational platform in test (app and WhatsApp): completed Pix transfers +69%, Pix-key typing errors −21%, value moved +4.2%. — [Cliente S.A.](https://portal.clientesa.com.br/bb-lanca-plataforma-de-ia-para-transformar-atendimento-em-conversas/); [Canaltech](https://canaltech.com.br/apps/banco-do-brasil-testa-ia-que-troca-menus-por-conversa-no-app-e-whatsapp/)
- Itaú ia.i:
  - Beta from Jul 27, 2026 to 300k clients; target 3M by end of September and the full base by December.
  - Text or voice. Pix is the only transactional operation enabled.
  - CTO Carlos Eduardo Mazzei: "Não teremos alucinações com informações factuais" ("We won't have hallucinations with factual information"); facts are verified in real time before display.
  - Source: [IT Forum](https://itforum.com.br/noticias/itau-libera-ia-i-assistente-de-ia-no-app-para-300-mil-clientes/)

**Pattern E — Collections and payment-plan negotiation**
- Banco do Brasil, WhatsApp debt-renegotiation agent (BBTS + AWS + BRQ, Jul 2026):
  - Results: conversions +306%; 50% of interactions completed with no human; average installments per agreement fell from 33.17 to 14.22.
  - Flow: identify intent → simulate personalized conditions → check account → formalize the agreement → issue the boleto.
  - Source: [IT Forum](https://itforum.com.br/noticias/banco-do-brasil-ia-whatsapp/)
  - An earlier CNN Brasil report: about R$7M refinanced and about 800 agreements in roughly the first month; target R$100M for the year. — [CNN Brasil](https://www.cnnbrasil.com.br/tecnologia/quitar-divida-por-whatsapp-banco-do-brasil-refinanciou-r-7-mi-em-um-mes/)
- Bradesco: AI monitors about 18,000 collection calls a day and coaches human operators on approach and product offers ("IA helps the human operator negotiate better"). — [Bloomberg Línea](https://www.bloomberglinea.com.br/negocios/ia-generativa-resolve-82-dos-atendimentos-iniciais-no-bradesco-diz-diretora/)
- Mercado Pago: loans/credit is 16.5% of agent use, including debt renegotiation. — [Mobile Time](https://www.mobiletime.com.br/noticias/13/02/2026/mercado-pago-agente-ia/)
- Banco Hipotecario (AR): "agentes con videos de inteligencia artificial" negotiate based on the client's payment capacity; AI analyses call-center conversations to classify the cause of default (job loss, insufficient income, intentional non-payment). — [Infobae, May 2026](https://www.infobae.com/economia/2026/05/22/una-app-diferente-para-cada-cliente-y-algoritmos-que-negocian-creditos-como-cambian-los-bancos-con-la-llegada-de-la-ia/)
- Vendor claims (Brazil):
  - Monest's agent "Mia": 6M+ negotiation conversations and R$500M in agreements since Jan 2024; "ROI 226% higher" than humans; R$15.95 per agreement. [vendor claim] — [Fincatch](https://www.fincatch.com.br/post/ia-ja-negocia-mais-de-r-500-milhoes-em-dividas-no-brasil)
  - Banco BMG: agreement rate +40% with O2OBOTS; 79% of issued boletos converted. [vendor claim] — [O2OBOTS](https://www.o2obots.com/blog/agente-ia-renegociacao-dividas-whatsapp-o2obots)

**Pattern F — Proactive fraud confirmation ("¿reconoces esta compra?")**
- Bancolombia: Tabot writes from its verified WhatsApp number (+57 301 353 6788) when it detects unusual movements. The customer replies only "SI" or "NO". It never asks for passwords or card data. — [Bancolombia FAQ](https://www.bancolombia.com/centro-de-ayuda/preguntas-frecuentes/por-que-me-llegan-mensajes-de-confirmacion-whatsapp); [Bancolombia](https://www.bancolombia.com/acerca-de/sala-prensa/noticias/productos-servicios/como-reconocer-tabot-oficial)
- CBA: AI systems send more than 40,000 proactive alerts a day, and fraud losses fell more than 20% in 1H FY26 vs 1H FY25. [bank-reported, via bank-affiliated site] — [BCA / CBA](https://www.bca.com.au/our-insights/business-stories/cba-deploying-ai-at-scale-to-help-protect-customers-against-scams-and-financial-crime/)
- Risk: scammers impersonate Bancolombia advisors on WhatsApp ("falsos asesores"). — [El Universal (CO)](https://www.eluniversal.com.co/colombia/2025/07/21/asi-operan-los-falsos-asesores-de-bancolombia-que-estafan-por-whatsapp/)

**Pattern G — Pre-payment scam interrogation and scam checker (APP / Pix scams)**
- Starling (UK):
  - Scam Intelligence launched Oct 27, 2025. Customers upload screenshots of marketplace listings or messages; Gemini analyzes them for red flags (unrealistic price, fake images, mismatched seller bank details, urgency). Opt-in. — [Starling](https://www.starlingbank.com/news/scam-intelligence-launch/)
  - The 2025 marketplace version raised the rate at which customers cancelled suspicious marketplace payments by 300%.
  - A Scam Intelligence agent inside Starling Assistant (launched Mar 2026) covers 10+ scam types. When a customer is about to pay, it asks targeted questions before funds move. — [The Paypers](https://thepaypers.com/fraud-and-fincrime/news/starling-bank-adds-ai-agent-to-detect-romance-and-investment-fraud)
- CBA:
  - Gen AI Scam Checker (screenshot of an SMS → instant analysis) in the Truyu app. Customer scam losses fell 76% (2H25 vs 1H23) from a broader set of tools. Aug 11, 2025. — [CommBank](https://www.commbank.com.au/articles/newsroom/2025/08/commbank-customer-scam-losses-fall-truyu.html)
  - Apate.ai conversational bots engage scammers to harvest intelligence. — [CommBank](https://www.commbank.com.au/articles/newsroom/2025/06/apate-ai.html)
- Brazil's regulatory context:
  - Pix participants must build scam alerts for atypical transactions from 2025; each institution designs its own criteria. — [CNN Brasil](https://www.cnnbrasil.com.br/economia/macroeconomia/pix-bc-obriga-bancos-a-criarem-alerta-de-golpe-a-partir-de-2025/)
  - Mercado Pago plans to integrate a "Blind Mode" security feature into its agent. — [Mobile Time](https://www.mobiletime.com.br/noticias/13/02/2026/mercado-pago-agente-ia/)

**Pattern H — Scam-victim support and dispute filing (Pix MED 2.0, chargebacks)**
- Brazil MED 2.0 timeline:
  - Oct 1, 2025: self-service dispute ("botão de contestação") inside the Pix area of every bank app, with no call to service required.
  - Nov 23, 2025: tracing funds across multiple accounts becomes optional. Feb 2026: mandatory.
  - Refund within up to 11 days of the dispute.
  - Source: [Agência Brasil](https://agenciabrasil.ebc.com.br/economia/noticia/2025-08/pix-novas-regras-vao-facilitar-devolucao-de-valores-em-casos-de-golpe)
  - After a dispute, funds are blocked for 7 days while the banks analyse it. — [search summary of ISTOÉ Dinheiro and others](https://istoedinheiro.com.br/pix-botacao-de-contestacao-como-usar)
- CFPB (background, 2023): chatbots failed to open disputes. One complainant: the "chat agent confirmed that the agent from the prior...did NOT open a dispute" despite a promised provisional credit. The CFPB says institutions must "accurately recognize when disputes are raised." — [CFPB](https://www.consumerfinance.gov/data-research/research-reports/chatbots-in-consumer-finance/chatbots-in-consumer-finance/)
- Chargeback automation: vendors describe end-to-end agents (intake → classify → evidence → Reg E/network deadlines → customer status → audit log). No bank-reported dispute-agent metrics were found. [vendor claim] — [Lorikeet](https://www.lorikeetcx.ai/articles/best-ai-payment-dispute-chargeback-automation-2026); [HCLTech case study](https://www.hcltech.com/case-study/reimagining-financial-workflows-with-ai-driven-chargeback-automation)
- Visa, Mastercard and Amex are activating AI-agent payments in 2026, but "post-transaction infrastructure… to manage disputes… remains almost entirely unaddressed." [vendor/industry commentary] — [Chargebacks911 via Finopotamus](https://www.finopotamus.com/post/chargebacks911-warns-ai-agents-are-creating-a-new-era-of-dispute-risk-for-merchants-and-banks)

**Pattern I — Complaint (PQR/reclamo) intake and response drafting**
- Banco de Bogotá (CO):
  - 30% of PQRS are already filed through a generative-AI flow. The bank is working toward AI that understands the complaint, checks bank databases and internal policies, and drafts the final response. May 2025.
  - The article is paywalled; these figures come from the search summary. — [iupana](https://iupana.com/2025/05/22/los-15-casos-de-uso-de-ia-generativa-que-desarrolla-banco-de-bogota-desde-reclamos-hasta-oportunidades-comerciales/)
- Banco BV (BR), WhatsApp agents built by Jabuti AGI: up to a 73% reduction in repeat contacts within 30 days; Dec 9, 2025. [bank/vendor] — [TI Inside](https://tiinside.com.br/09/12/2025/banco-bv-escala-uso-de-agentes-de-ia-para-transformar-atendimento-via-whatsapp/)
- Banco Inter (BR): reportedly credits genAI in service with improving its position in complaint rankings (Banco Central, Reclame Aqui). [secondary, search summary only] — [Seu Dinheiro](https://www.seudinheiro.com/2026/empresas/a-nova-guerra-dos-bancos-como-a-inteligencia-artificial-vai-mudar-a-disputa-pela-principalidade-miql/)

**Pattern J — Agent-assist copilot and summaries for human agents**
- NatWest: more than 70,000 hours saved through automated AI call summaries in retail. Cora+ genAI showed a 150% improvement in customer satisfaction while reducing colleague interventions. GenAI journeys grew from 4 to 21 by end-2025. — [Computer Weekly / NatWest (search summary)](https://www.computerweekly.com/news/366639140/NatWest-hails-progress-after-12bn-spent-on-tech-last-year-but-true-AI-transformation-to-come); [FStech](https://www.fstech.co.uk/fst/Thousands_Of_NatWest_Customers_To_Soon_Have_Access_To_Agentic_Financial_Assistant.php)
- Banco do Brasil + NiCE Copilot (pilot, Jul 2026): interaction summaries, contact history and sentiment in one workspace. WhatsApp was integrated into BB's NiCE contact center in 2025. — [Inforchannel](https://inforchannel.com.br/2026/07/14/banco-do-brasil-leva-copilot-da-nice-ao-atendimento-e-aposta-em-ia-generativa/)
- Banco Galicia (AR): "Agent Copilot" for staff expected in H2 2025. — [La Nación](https://www.lanacion.com.ar/economia/IA/un-cambio-cultural-banco-galicia-apuesta-por-la-ia-generativa-para-transformar-la-atencion-al-nid30062025/)
- U.S. Bank: real-time agent assistance with Amazon Q in Connect + Bedrock (Claude); transcribes calls and recommends actions. [vendor/secondary] — [ZenML LLMOps DB](https://www.zenml.io/llmops-database/real-time-ai-agent-assistance-in-contact-center-operations)
- JPMorgan (Investor Day, May 2025): servicing calls down nearly 30% per account and accounts serviced per ops headcount up 25%. The bank notes much of this is process automation, not only AI. — [JPMC Investor Day 2025 transcript (search summary)](https://www.jpmorganchase.com/content/dam/jpmc/jpmorgan-chase-and-co/investor-relations/documents/events/2025/jpmc-2025-investor-day/full-transcript.pdf)

**Pattern K — Live social-engineering / "coaching" detection during a conversation**
- Westpac (AU), pilot with its scam team, May 29, 2025: the AI call assistant detects signs a customer is about to pay a scammer and whether "a customer is being coached by a scammer in the background". It also guides operators in real time. — [Retail Banker International](https://www.retailbankerinternational.com/news/westpac-ai-assistant-scams/)

**Pattern L — Vulnerable-customer detection**
- The FCA cites AI that identifies characteristics of vulnerability as good practice. — [Dentons on FCA vulnerable-customer review, Apr 2025](https://www.dentons.com/en/insights/articles/2025/april/3/fca-vulnerable-customer-review); [FCA AI approach](https://www.fca.org.uk/firms/innovation/ai-approach)
- A vendor claims the FCA found 58% of vulnerable customers don't disclose their circumstances. [vendor claim; primary FCA source not verified] — [search summary of Aveni/Voyc blogs](https://voyc.ai/fca-vulnerable-customers-best-practice/)

**Pattern M — Voice agent replacing the IVR**
- BBVA México, "Blue" (scaled from June 2025; covered below under Q2 and Q5):
  - About 63M calls a year. The old IVR had 40+ options, waits of up to 4 minutes, and about 1 in 2 calls abandoned.
  - Blue handles or routes calls in about 30 seconds, with 95% effectiveness and 5% "errors or hallucinations".
  - Calls start from the app, so the customer is already authenticated.
  - Source: [DPL News](https://dplnews.com/bbva-mexico-asistente-ia-generativa-tiempos-atencion-30-segundos/)

**Pattern N — Orchestrator ("one agent, many sub-agents")**
- Mercado Pago (Oct 2025, BR):
  - A single visible agent orchestrates hidden specialist agents. It accepts text, audio and images and can act for the customer (pay bills, schedule and execute Pix).
  - Intent mix: credit card 20.4%, loans/credit 16.5%, Pix 12.0%, account management 7.1% (identity validation, access recovery), POS devices 6.5%.
  - Source: [Mobile Time](https://www.mobiletime.com.br/noticias/13/02/2026/mercado-pago-agente-ia/)
  - "Mago" launched in Mexico in Sep 2026. — [Fast Company México](https://fastcompany.mx/2026/09/23/mago-mercado-pago-asistente-ia-mexico/)

### Inferences
- The loop that matters for "agentic" is **act + verify**. The strongest public designs are:
  - Monzo: phased autonomy from human-reviewed Q&A → runbooks → tools, with confidence-gated escalation and a golden test set.
  - Wells Fargo: PII scrubbed by a small model before the LLM.
  - Itaú: facts verified before display, and only Pix enabled.
  - Nubank: low per-transaction caps on WhatsApp, plus the same fraud engine as the app.

  A hackathon team that shows an explicit verification step (read-back confirmation, limits, idempotent tool calls, post-action checks) would match what production banks actually do.
- Patterns F → H → C chain naturally: fraud confirmation "NO" → block the card → open a dispute or MED → order a replacement → keep the customer updated. No bank's public materials describe this closed loop end to end; each piece is deployed separately. That makes the chain a strong novelty argument.
- Collections (E) has the hardest LATAM ROI evidence (BB +306%, 50% without humans). It is also regulated (see Q2), so a negotiation agent with affordability and contact-frequency guardrails is differentiated.

### Gaps
- No bank-reported metrics were found for autonomous dispute or chargeback resolution in LATAM. The chargeback figures that surfaced (−60% turnaround, −35% handle time) come from vendor pages whose exact attribution I could not verify.
- I found no bank-reported deployment of **AI-mediated real-time translation** between customer and human agent in retail banking. Only generic vendor material exists ([Parloa](https://www.parloa.com/knowledge-hub/ai-contact-center-language-translation-process/)).
- VentureBeat says Fargo's "Spanish usage has surged, accounting for more than 80% of usage since its September 2023 rollout". The wording is ambiguous: it may mean 80% of usage growth. Treat with caution.
- No bank-reported **retention/cancellation agent** in retail banking was found.
- The Banco de Bogotá PQRS details and the full Davivienda use cases are paywalled on iupana.

---

## Q2. LATAM deployments: who runs what, in which channels (is WhatsApp dominant?), with what numbers?

### Takeaway
LATAM incumbents and fintechs have reported some of the world's highest AI containment numbers: Bradesco 82%, Nubank >60% at human parity, Nequi 80%. WhatsApp is the dominant channel for service, fraud confirmation and especially collections (BB, BV, Bancolombia, Galicia, Nubank Pix). However, **transactional agents are increasingly launched in-app** (Itaú ia.i, Mercado Pago, BBVA México's app-originated voice). The likely reasons are authentication and WhatsApp impersonation scams.

### Cited Findings

**Brazil**
- **Nubank:**
  - >60% of support conversations handled by AI agents at or above human parity (Q2 2026). — [Nu Q2 2026](https://nu.com/en/newsroom/company/nu-holdings-ltd-reports-second-quarter-2026-financial-results)
  - Pix by voice, text or image in the app and on WhatsApp. — [Nu newsroom](https://nu.com/en/newsroom/consumers/nubank-leverages-ai-to-scale-pix-operations)
  - Partnership giving customers ChatGPT Go (Oct 2025). — [TI Inside](https://tiinside.com.br/28/10/2025/chatgpt-premium-chega-ao-brasil-por-r3999-ou-de-graca-para-clientes-da-nubank/)
- **Bradesco (BIA):**
  - 82% of initial service requests resolved by genAI; 10M+ chat users; collections copilot on about 18k calls a day (Oct 2025). — [Bloomberg Línea](https://www.bloomberglinea.com.br/negocios/ia-generativa-resolve-82-dos-atendimentos-iniciais-no-bradesco-diz-diretora/)
  - 3M genAI BIA customers with ~90% resolution. — [Finsiders Brasil](https://finsidersbrasil.com.br/tecnologia-para-fintechs/uso-da-ia-pelos-bancos-avanca-para-alem-do-atendimento/)
- **Itaú:**
  - ia.i beta Jul 27, 2026 (300k clients → full base by December). Pix is the only transaction enabled. — [IT Forum](https://itforum.com.br/noticias/itau-libera-ia-i-assistente-de-ia-no-app-para-300-mil-clientes/)
  - 1.3k+ AI models in use (Mar 2026). — [Mobile Time](https://www.mobiletime.com.br/noticias/09/03/2026/itau-modelos-ia/)
  - WhatsApp renegotiation channel exists. — [Itaú](https://www.itau.com.br/atendimento-itau/para-voce/whatsapp-itau-renegociacao)
- **Banco do Brasil:**
  - Conversational platform tests: Pix +69%, key errors −21%. — [Canaltech](https://canaltech.com.br/apps/banco-do-brasil-testa-ia-que-troca-menus-por-conversa-no-app-e-whatsapp/)
  - WhatsApp debt renegotiation: +306% conversions, 50% no-human. — [IT Forum](https://itforum.com.br/noticias/banco-do-brasil-ia-whatsapp/)
  - NiCE Copilot pilot. — [Inforchannel](https://inforchannel.com.br/2026/07/14/banco-do-brasil-leva-copilot-da-nice-ao-atendimento-e-aposta-em-ia-generativa/)
- **Santander Brasil:** part of a €50M group genAI investment; the 2027 plan expects virtual assistants to complete full transactions; a genAI copilot helps human chat agents. [secondary, search summary] — [Convergência Digital](https://convergenciadigital.com.br/mercado/santander-investe-50-milhoes-de-euros-em-ia-generativa-brasil-tem-papel-chave/)
- **Mercado Pago:** orchestrator agent since Oct 2025, with the intent mix listed under Pattern N. — [Mobile Time](https://www.mobiletime.com.br/noticias/13/02/2026/mercado-pago-agente-ia/)
- **Banco BV:** WhatsApp agents; up to −73% repeat contacts within 30 days. — [TI Inside](https://tiinside.com.br/09/12/2025/banco-bv-escala-uso-de-agentes-de-ia-para-transformar-atendimento-via-whatsapp/)
- **Sector (Febraban 2025 tech survey, via a secondary summary):**
  - 94% of banks use genAI to improve customer service or experience.
  - 88% are increasing interaction via instant-messaging apps.
  - 81% are expanding transactions via chatbots.
  - Average efficiency gain from AI of 11.4%.
  - Sources: [Dock summary](https://dock.tech/fluid/blog/financeiro/pesquisa-febraban-de-tecnologia-bancaria/); [Febraban PDF](https://cmsarquivos.febraban.org.br/Arquivos/documentos/PDF/Pesquisa%20Febraban%20de%20Tecnologia%20Banca%CC%81ria%202025%20-%20Vol_01%20-%205.pdf)
- **Regulation:**
  - The SAC decree (Decreto 11.034/2022; background, still in force) applies to banks. It requires a human telephone channel for at least 8 h/day and at least one channel (e.g., WhatsApp or chatbot) available 24/7. — [Evolux](https://evolux.net.br/novo-decreto-do-sac-entenda-o-que-muda/); [Conjur](https://conjur.com.br/2024-dez-23/novo-sac-obriga-atendimento-humano-e-ataca-problemas-recorrentes-na-justica/)
  - Pix scam-alert mandate (2025) and MED 2.0 (see Q1, Patterns G and H).

**Mexico**
- **BBVA México "Blue":** voice agent replacing the IVR (June 2025); 63M calls a year; routes in about 30 s; 95% effective with 5% errors or hallucinations; calls originate in the app for authentication. — [DPL News](https://dplnews.com/bbva-mexico-asistente-ia-generativa-tiempos-atencion-30-segundos/)
- **Mercado Pago:** "Mago" launched in Mexico, Sep 2026. — [Fast Company MX](https://fastcompany.mx/2026/09/23/mago-mercado-pago-asistente-ia-mexico/)
- **Banorte:** "Maya" assistant (2022, background) answers about 400 intents and performs 18 transactions on web and app. — [Forbes México](https://forbes.com.mx/inteligencia-artificial-es-clave-para-agilizar-y-mejorar-servicios-banorte/)
- **WhatsApp Business AI:** Meta launched native AI agents on Nov 3, 2025, with Mexico the first country. By early 2026, Mexico and the Philippines together had more than 1M weekly conversations. Global launch Jun 3, 2026. [secondary] — [Ecosistema Startup](https://ecosistemastartup.com/whatsapp-business-lanza-agente-ia-global-en-2026/); [Informador](https://www.informador.mx/tecnologia/whatsapp-business-meta-lanza-nuevos-agentes-de-ia-20260617-0211.html)
- **Collections regulation:** CONDUSEF regulates collection agencies through REDECO and prohibits harassment. [secondary/vendor] — [Dapta](https://dapta.ai/es/blog-posts/agentes-de-voz-con-ia-para-cobranza/)

**Colombia**
- **Bancolombia Tabot:** WhatsApp and web; card block/unblock, certificates, suspicious-message reporting, proactive SI/NO fraud confirmation from its verified number. — [Bancolombia](https://www.bancolombia.com/acerca-de/sala-prensa/noticias/productos-servicios/como-reconocer-tabot-oficial); [Bancolombia FAQ](https://www.bancolombia.com/centro-de-ayuda/preguntas-frecuentes/por-que-me-llegan-mensajes-de-confirmacion-whatsapp)
- **Nequi:** 80% of interactions handled by AI, with immediate human escalation (Aug 2026). — [El Colombiano](https://www.elcolombiano.com/tecnologia/nequi-inteligencia-artificial-credito-atencion-cliente-machine-learning-colombia-NF39695697)
- **Davivienda / DaviPlata:**
  - "El Profe de Finanzas", a genAI financial-education assistant open to non-customers. — [Factor de Éxito](https://www.revistafactordeexito.com/a/39269/davivienda-creo-un-nuevo-asistente-de-finanzas-personales-con-inteligencia-artificial)
  - DaviPlata announced AI for transactions by voice and chat. — [El Espectador](https://www.elespectador.com/tecnologia/gadgets-y-apps/daviplata-anuncio-que-integrara-funciones-de-ia-para-realizar-transacciones/)
- **Banco de Bogotá:** 30% of PQRS filed via a genAI flow. [paywalled; from search summary] — [iupana](https://iupana.com/2025/05/22/los-15-casos-de-uso-de-ia-generativa-que-desarrolla-banco-de-bogota-desde-reclamos-hasta-oportunidades-comerciales/)
- **Collections regulation:** Ley 2300 of 2023 ("dejen de fregar") limits the hours and frequency of debtor contact. [secondary/vendor] — [Dapta](https://dapta.ai/es/blog-posts/agentes-de-voz-con-ia-para-cobranza/)

**Argentina**
- **Banco Galicia:** "Gala" WhatsApp assistant, 5M+ interactions in 2024; 44M+ interactions across channels; Agent Copilot planned for H2 2025. The bank says it sends only queries to genAI, not personal data. — [La Nación](https://www.lanacion.com.ar/economia/IA/un-cambio-cultural-banco-galicia-apuesta-por-la-ia-generativa-para-transformar-la-atencion-al-nid30062025/)
- **Banco Macro:** agents adapt the app per user, e.g., suggest routine payments for one-click approval; 85% of operations use ML/genAI. — [Infobae](https://www.infobae.com/economia/2026/05/22/una-app-diferente-para-cada-cliente-y-algoritmos-que-negocian-creditos-como-cambian-los-bancos-con-la-llegada-de-la-ia/)
- **Banco Hipotecario:** AI negotiation based on payment capacity; call-center analytics classify the reason for default. — [Infobae](https://www.infobae.com/economia/2026/05/22/una-app-diferente-para-cada-cliente-y-algoritmos-que-negocian-creditos-como-cambian-los-bancos-con-la-llegada-de-la-ia/)
- **Supervielle:** WhatsApp self-service, now building transaction agents. — [Infobae](https://www.infobae.com/economia/2026/05/22/una-app-diferente-para-cada-cliente-y-algoritmos-que-negocian-creditos-como-cambian-los-bancos-con-la-llegada-de-la-ia/)
- **Ualá:** public AI statements focus on credit scoring and employee productivity, not a customer-service agent. — [Infobae](https://www.infobae.com/economia/2026/05/22/una-app-diferente-para-cada-cliente-y-algoritmos-que-negocian-creditos-como-cambian-los-bancos-con-la-llegada-de-la-ia/)

**WhatsApp dominance**
- WhatsApp has 530M+ MAU in LATAM (87% smartphone penetration); >90% of internet users in Brazil, Mexico and Colombia use it; WhatsApp debt-recovery campaigns are "20% more effective". [vendor/aggregator claims] — [Latinia](https://latinia.com/en/resources/conversational-banking); [Statista](https://www.statista.com/statistics/1323702/whatsapp-penetration-latin-american-countries/)

### Inferences
- **WhatsApp is dominant, but not universal.** It is confirmed as the main channel for Tier-1 service (Galicia, Tabot, BV), outbound fraud confirmation (Bancolombia) and collections (BB, Itaú, BMG).

  The flagship transactional agents of 2025–26 (Itaú ia.i, Mercado Pago, Nubank's primary flow, BBVA's app-authenticated voice) live in the app. Nubank keeps low caps on WhatsApp Pix. A credible hackathon design is **WhatsApp for outreach, notification and low-risk intents, with a hand-off to in-app step-up authentication for money movement.**
- The Brazilian SAC decree and Nequi's "no barrier" escalation show that human access is a **compliance feature**, not just UX, in LATAM.

### Gaps
- There are no public AI customer-service metrics for Banorte (post-2022), Galicia (containment %), Macro, Ualá, Banco Inter, Santander Brasil or Davivienda (containment or CSAT).
- A widely quoted figure puts 2025 Pix scam losses at R$6.5bn. I could not trace it to a primary source (Banco Central or Febraban), so it is left out of the findings.
- Colombia reportedly had 218k+ digital-fraud claims in H1 2025 (attributed to Asobancaria in [LatinPyme](https://latinpyme.com/blog/revista-latinpyme-2/ia-y-fraude-financiero-el-contexto-como-nueva-defensa-1191)). This is unverified at source.
- BBVA México Blue's accuracy is reported as 95% effective/5% errors (DPL News). Search summaries of other outlets say "92% understanding". The two figures conflict; neither is audited.
- Headline says 73% of Colombian banks use AI ([La República](https://www.larepublica.co/finanzas/la-inteligencia-artificial-ya-esta-presente-en-73-de-las-entidades-bancarias-en-el-pais-4095716)); not verified in body text.

---

## Q3. Global reference points with published outcomes, and what went wrong (Klarna, Erica, CBA, JPMorgan, Wells Fargo, NatWest, Revolut, Monzo, Lloyds; CFPB, doom loops, Air Canada)

### Takeaway
Scale leaders (Erica, Fargo, Cora) show that **proactive, narrow and well-governed** assistants reach billions of interactions. The high-profile failures are all "replace humans or cut costs first" moves:
- Klarna publicly reversed course in May 2025.
- CBA reversed 45 voice-bot job cuts in Aug 2025 after call volumes *rose*.
- Air Canada was held liable for a chatbot's invented policy.
- The CFPB documented doom loops and missed disputes.

### Cited Findings
- **Klarna:**
  - Feb 2024: 2.3M chats in month one, equal to about 700 agents.
  - May 2025: the CEO admitted cost was "too predominant" and led to "lower quality". Klarna re-hired humans in an "Uber-type" flexible model and guarantees access to a human.
  - AI still handles about two-thirds of inquiries, with repeat issues down 25%.
  - Source: [CX Dive](https://www.customerexperiencedive.com/news/klarna-reinvests-human-talent-customer-service-AI-chatbot/747586/)
  - Q3 2025: 853 FTE-equivalent, $60M saved, CSAT "on-par". — [CX Dive](https://www.customerexperiencedive.com/news/klarna-says-ai-agent-work-853-employees/805987/)
- **Bank of America Erica (Aug 2025):**
  - 3B+ total interactions; 58M+ a month; nearly 50M users; 1.7B proactive personalized insights; 98% of users "find needed information".
  - Erica for Employees is used by 90%+ of staff and cut IT service-desk calls by 50%.
  - Source: [BofA newsroom](https://newsroom.bankofamerica.com/content/newsroom/press-releases/2025/08/a-decade-of-ai-innovation--bofa-s-virtual-assistant-erica-surpas.html)
  - About 50–60% of Erica interactions are proactive (the bot suggests first). — [CX Dive](https://www.customerexperiencedive.com/news/bank-of-america-erica-virtual-assistants/758334/)
- **Wells Fargo Fargo:**
  - 245.4M interactions in 2024, more than double projections. PII is scrubbed by an internal small model before any call to Gemini Flash 2.0; "zero humans in the loop". — [VentureBeat](https://venturebeat.com/ai/wells-fargos-ai-assistant-just-crossed-245-million-interactions-with-zero-humans-in-the-loop-and-zero-pii-to-the-llm)
  - More than 1B interactions cumulatively (2026). — [Investing.com](https://www.investing.com/news/company-news/wells-fargos-ai-assistant-fargo-surpasses-1-billion-interactions-93CH-4583153)
- **NatWest Cora:** 12.9M retail conversations in 2025; Cora+ +150% CSAT; agentic money-management assistant for 25k customers by end of Q1 2026 (OpenAI models). — [FStech](https://www.fstech.co.uk/fst/Thousands_Of_NatWest_Customers_To_Soon_Have_Access_To_Agentic_Financial_Assistant.php)
- **Commonwealth Bank (CBA):**
  - **Success:** customer scam losses −76% (2H25 vs 1H23); Gen AI Scam Checker; more than A$900M invested in FY25 in fraud, scams and cyber. — [CommBank](https://www.commbank.com.au/articles/newsroom/2025/08/commbank-customer-scam-losses-fall-truyu.html)
  - **Failure:** in July 2025 CBA cut 45 roles after launching an AI voice-bot. On Aug 21, 2025 it reversed the cuts and apologised ("we did not adequately consider all relevant business considerations"). The union said call volumes rose after the bot launched, with managers offering overtime and pulling team leaders onto the phones. — [ABC News](https://www.abc.net.au/news/2025-08-21/cba-backtracks-on-ai-job-cuts-as-chatbot-lifts-call-volumes/105679492)
- **JPMorgan (Investor Day 2025):** servicing calls down nearly 30% per account; accounts per ops headcount +25%; processing costs −15%. Partly process automation, not only AI. — [JPMC transcript (search summary)](https://www.jpmorganchase.com/content/dam/jpmc/jpmorgan-chase-and-co/investor-relations/documents/events/2025/jpmc-2025-investor-day/full-transcript.pdf)
- **Monzo:** Ops Agent covers 150+ intents; +10 pp resolution on transaction queries; phased autonomy. — [Conversational AI News](https://www.conversationalainews.com/how-monzo-bank-built-their-own-ai-agent-for-live-customer-support-without-losing-control/)
- **Revolut AIR:** Apr 9, 2026, 13M UK customers; card freeze, subscriptions, travel eSIM. — [FinTech Weekly](https://www.fintechweekly.com/news/revolut-air-ai-assistant-uk-customers-launch-2026)
- **Lloyds:**
  - Agentic financial assistant for early 2026, for 21M+ customers, with human hand-off "when required". — [FinTech Global](https://fintech.global/2025/11/06/lloyds-unveils-uks-first-ai-financial-assistant/)
  - Tested with about 7,000 employees across 12,000 trials. Customers can query a payment and the assistant carries out the transaction. — [Retail Banker International](https://www.retailbankerinternational.com/news/lloyds-banking-ai-financial-assistant/)
  - Lloyds' own survey: 80% of AI users worry about inaccurate information. — [FinTech Global](https://fintech.global/2025/11/06/lloyds-unveils-uks-first-ai-financial-assistant/)
- **Starling:** Scam Intelligence (Oct 2025); +300% cancellations of suspicious marketplace payments; agent version in Starling Assistant (Mar 2026). — [Starling](https://www.starlingbank.com/news/scam-intelligence-launch/); [The Paypers](https://thepaypers.com/fraud-and-fincrime/news/starling-bank-adds-ai-agent-to-detect-romance-and-investment-fraud)
- **Westpac:** live scam-coaching detection pilot (May 2025). — [RBI](https://www.retailbankerinternational.com/news/westpac-ai-assistant-scams/)
- **CFPB "Chatbots in consumer finance" (June 2023, background):**
  - About 37% of the US population (98M+ people) used a bank chatbot in 2022.
  - Harms: "doom loops" without an off-ramp to a human; inaccurate information; failure to recognize disputes; privacy.
  - Cited surveys: 80% of chatbot users left frustrated; 78% needed a human afterward.
  - Source: [CFPB](https://www.consumerfinance.gov/data-research/research-reports/chatbots-in-consumer-finance/chatbots-in-consumer-finance/)
  - Aug 2024: the CFPB said it would propose rules to make it easier to reach a human and end doom loops. — [Consumer Finance Monitor](https://www.consumerfinancemonitor.com/2024/08/13/cfpb-to-issue-proposal-to-make-it-easier-for-consumers-to-reach-real-person-when-seeking-assistance/)
- **Moffatt v. Air Canada (2024 BCCRT 149, Feb 2024):**
  - The chatbot invented a retroactive bereavement-refund policy. The tribunal held the airline liable for negligent misrepresentation, rejected the argument that the chatbot was "a separate entity", and awarded CA$812.02. — [Wikipedia](https://en.wikipedia.org/wiki/Moffatt_v._Air_Canada); [ABA Business Law Today](https://www.americanbar.org/groups/business_law/resources/business-law-today/2024-february/bc-tribunal-confirms-companies-remain-liable-information-provided-ai-chatbot/)
- **Voice authentication risk:** on Jul 22, 2025 at a Federal Reserve conference, Sam Altman said some institutions still accept voiceprints and "AI has fully defeated that". — [Fortune](https://fortune.com/2025/07/24/sam-altman-fraud-crisis-ai-voice-mimicking-federal-reserve/)

### Inferences
- The failure modes are consistent:
  1. Optimising for deflection or cost instead of resolution (Klarna, CBA).
  2. No reliable human off-ramp (CFPB doom loops).
  3. Generating policy instead of retrieving it (Air Canada).
  4. Failing to detect a legally significant event such as a dispute (CFPB).

  Designs that make escalation a first-class action, cite the policy source, and auto-detect "dispute/complaint/vulnerability" triggers directly address documented regulatory and judicial failures.
- CBA shows that a bot can *increase* contact volume, likely through failed containment and repeat calls. Hackathon metrics should therefore include repeat-contact rate (as BV reports) and not only containment.

### Gaps
- The CFPB's 2024 plan to propose doom-loop rules: I found no evidence it was finalized. It likely stalled under the 2025 CFPB changes, but this is unverified.
- JPMorgan has not published customer-facing chatbot metrics.
- Revolut and Lloyds post-launch outcome metrics were not found.

---

## Q4. What is commodity (what ~180 hackathon teams will build) vs genuinely novel in 2026? Analyst views

### Takeaway
Analysts say agentic customer service is mainstream in intent but thin in production:
- Evident: only 9 of 50 top banks had a documented agentic use case in 2025, rising to 31% of new use cases being agentic in Q1 2026.
- Gartner: 80% autonomous resolution predicted by 2029, but also predicted rehiring and a strong customer demand for a human option.
- Forrester: one-third of brands will erode trust with premature genAI self-service in 2026.

**Commodity:** RAG FAQ bots, balance/transaction lookup, card block, spending insights, conversational transfers, and "summary + handoff".
**Rare:** scam interrogation before payment, scam-victim recovery flows, closed-loop fraud → dispute, affordability-aware negotiation, live coaching or vulnerability detection, and serving customers' *own* AI agents.

### Cited Findings
- **Evident:**
  - Q1 2026: "Nearly 1 in 3 AI use cases reported in Q1 were agentic" (31%), up from 15% in Q4 2025. They are concentrated in product and service operations, and banks are shifting from broad copilots to workflow-embedded AI. — [Evident Q1 2026](https://evidentinsights.com/insights/banking-use-case-trends-q1-2026)
  - 2025 Index: only 9 of the 50 banks tracked had documented an agentic use case in production or pilot.
  - Of genAI use cases, 15% are externally facing, and over half of those are in retail banking: upgrading legacy chatbots, virtual avatars, and experimenting with agentic workflows.
  - Source: [CIO Dive on Evident](https://www.ciodive.com/news/banks-accelerate-ai-adoption-agentic-automation-evident-insights/757463/)
- **Gartner, predictions and surveys:**
  - Agentic AI will autonomously resolve 80% of common customer-service issues by 2029, with a 30% operating-cost reduction (Mar 2025). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-03-05-gartner-predicts-agentic-ai-will-autonomously-resolve-80-percent-of-common-customer-service-issues-without-human-intervention-by-20290)
  - 50% of organizations will abandon plans to cut service headcount due to AI by 2027 (Jun 2025). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-06-10-gartner-predicts-50-percent-of-organizations-will-abandon-plans-to-reduce-customer-service-workforce-due-to-ai)
  - Only 20% of service leaders report AI-driven headcount reduction (Dec 2025). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-12-02-gartner-survey-finds-only-20-percent-of-customer-service-leaders-report-ai-driven-headcount-reduction)
  - Half of companies that cut service staff due to AI will rehire by 2027 (Feb 2026). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-02-03-gartner-predicts-half-of-companies-that-cut-customer-service-staff-due-to-ai-will-rehire-by-2027)
  - Unofficial third-party genAI tools will resolve 40% of service issues by 2027 (Dec 2024 prediction). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2024-12-16-gartner-predicts-unofficial-third-party-tools-powered-by-genai-will-resolve-40-percent-of-customer-service-issues-by-2027)
  - The following three surveys share one sample: 3,566 customers, fieldwork Feb–Mar 2026.
    - Customers are about 3x more likely to use third-party genAI (e.g., ChatGPT) than company chatbots. Third-party use nearly doubled in a year, while company-chatbot use has been flat since 2022 (Jul 2026). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-07-08-gartner-survey-finds-customers-are-three-times-more-likely-to-use-third-party-genai-than-company-provided-chatbots-for-customer-service); [Marketing Dive](https://www.marketingdive.com/news/customer-service-third-party-generative-ai-tools-brand-chatbots/824989/)
    - 87% say a human option is essential when genAI is used; 58% of genAI users have used it to complete a task on their behalf. Gartner advises against genAI as a mandatory first step (Aug 2026). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-08-04-gartner-survey-finds-87-percent-of-customers-say-companies-using-genai-for-customer-service-must-provide-access-to-a-human-agent0)
    - Only 27% would try a chatbot again after a negative experience. Only 7% used a chatbot in their most recent service interaction, though 49% say they would have. Gartner recommends "reliability over reach" (Sep 2026). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-09-02-gartner-finds-only-27-percent-of-customers-would-try-a-chatbot-again-after-a-negative-experience); [MacTech](https://www.mactech.com/2026/09/08/gartner-only-27-of-customers-would-try-a-chatbot-again-after-a-negative-experience/)
  - 64% of customers would prefer companies not use AI for service; the top fear is that reaching a person gets harder (Jul 2024, background-ish). — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2024-07-09-gartner-survey-finds-64-percent-of-customers-would-prefer-that-companies-didnt-use-ai-for-customer-service)
- **Forrester 2026 predictions (Oct 2025):** one-third of brands will erode customer trust through premature self-service genAI. — [Forrester](https://investor.forrester.com/news-releases/news-release-details/forresters-2026-b2c-marketing-cx-digital-business-predictions); [PPC Land](https://ppc.land/one-third-of-brands-will-damage-trust-with-ai-self-service-in-2026/)
- **McKinsey:** 35% of organizations plan to automate more than 60% of inbound inquiries by 2028; 62% expect authentication and call summaries to be fully automated. [search summary; page timed out, not verified] — [McKinsey](https://www.mckinsey.com/capabilities/operations/our-insights/operations-blog/agentic-ai-in-customer-care-whats-on-leaders-minds)
- **Customer-side AI agents already reach LATAM banks:** "Banco MCP", a third party, exposes read-only Open Finance Brasil data from Nubank, Itaú, Bradesco, Mercado Pago and others to ChatGPT and Claude via MCP. [third-party product, not a bank] — [Banco MCP docs](https://banco.mcp.ai/docs)

**Commodity vs novel classification** (this is my assessment; the evidence behind each rating is in the findings above)

| Use case | 2026 status in industry | Likely hackathon saturation | Novelty argument |
|---|---|---|---|
| RAG FAQ / policy Q&A | Ubiquitous (CFPB: all top-10 US banks had chatbots by 2023) | Very high | None; also Air Canada liability risk |
| Balance / transaction lookup, "explain this charge" | Widespread (Fargo, Erica, Mercado Pago's top intent) | Very high | Only if it uses merchant enrichment plus auto-dispute when unrecognized |
| Card block / unblock / freeze / replace | Widespread (Tabot, AIR, Monzo) | High | Low alone |
| Conversational Pix / transfer | Shipped by Nubank, BB, Itaú, Mercado Pago | High | Low; risky without caps or step-up auth |
| Spending insights / PFM chat | Widespread (NatWest, Lloyds, Revolut, Starling) | High | Low |
| Summary + human handoff / agent copilot | Widespread (NatWest, BB-NiCE, Nubank, Galicia) | Medium–high | Medium if the copilot does live compliance checks (dispute/vulnerability triggers) |
| Collections negotiation with affordability guardrails | Emerging (BB, BMG, Hipotecario; vendors) | Medium | Medium–high: hard ROI plus regulated contact rules (Ley 2300, REDECO) |
| Proactive fraud confirmation → auto-dispute/MED → card replacement (closed loop) | Pieces exist (Tabot SI/NO; MED 2.0 button); no public end-to-end loop found | Low–medium | High |
| Pre-payment scam interrogation (APP/Pix) | Rare (Starling, CBA; Westpac pilot); no LATAM bank found | Low | High, with a Pix scam-alert mandate tailwind |
| Scam-victim recovery companion (MED 2.0 filing, evidence, status, emotional triage) | New rails from Oct 2025 / Feb 2026; no AI deployment found | Low | High |
| Complaint (PQR/reclamo) auto-drafting with verification against core data | Early (Banco de Bogotá ~30% intake) | Low–medium | High in CO/MX/BR regulated-complaint context |
| Live social-engineering / coaching detection | Pilot (Westpac) | Low | High |
| Vulnerable-customer detection → specialist routing | UK regulatory good practice; rare in LATAM | Low | High |
| Serving customers' own AI agents (MCP / agent-to-agent) | Third-party only (Banco MCP); Gartner 3x stat | Very low | Very high, but security-heavy |
| AI-mediated translation (customer ↔ human agent) | Vendor-only evidence in banking | Low | Medium; weak LATAM demand evidence |

### Inferences
- Given Gartner's "3x third-party genAI" finding and flat company-chatbot adoption, the biggest strategic gap is that banks build bots customers don't choose. An "AI-first" system that also exposes safe, scoped tools to the customer's own assistant is differentiated. In Brazil, Open Finance already makes read-only access possible via third parties.
- "Reliability over reach" (Gartner, Sep 2026) plus Klarna and CBA argue for a pitch built on **few flows, closed loop, measurable resolution and repeat-contact rate**, not on breadth of intents.

### Gaps
- There is no published data on what hackathon teams typically build. The saturation column is inference.
- No Celent or BCG 2025–26 primary numbers on agentic customer service in banking were retrieved.
- The Evident full dataset is members-only.

---

## Q5. Proactive/outbound agents, voice-first agents, and human-in-the-loop "copilot + handoff": evidence and risks

### Takeaway
- **Proactive:** the strongest scale evidence. About half of Erica's interactions are proactive; CBA sends 40k alerts a day; Bancolombia runs SI/NO fraud confirmation.
- **Voice-first:** real wins (BBVA México) and a real failure (CBA voice-bot job-cut reversal), plus deepfake and voice-ID risk.
- **Copilot + handoff:** the lowest-risk pattern with solid outcomes (NatWest 70k hours; Bradesco collections coaching; Westpac scam coaching). Guaranteed human access is now both a customer expectation (Gartner 87%) and a legal requirement in places (Brazil SAC decree).

### Cited Findings
- **Proactive / outbound:**
  - Erica: 1.7B proactive insights; about 50–60% of interactions are proactive. — [BofA](https://newsroom.bankofamerica.com/content/newsroom/press-releases/2025/08/a-decade-of-ai-innovation--bofa-s-virtual-assistant-erica-surpas.html); [CX Dive](https://www.customerexperiencedive.com/news/bank-of-america-erica-virtual-assistants/758334/)
  - CBA: 40,000+ AI proactive alerts a day. — [BCA/CBA](https://www.bca.com.au/our-insights/business-stories/cba-deploying-ai-at-scale-to-help-protect-customers-against-scams-and-financial-crime/)
  - Bancolombia: WhatsApp SI/NO transaction confirmation from a verified number. — [Bancolombia FAQ](https://www.bancolombia.com/centro-de-ayuda/preguntas-frecuentes/por-que-me-llegan-mensajes-de-confirmacion-whatsapp)
  - BB collections on WhatsApp: +306% conversions. — [IT Forum](https://itforum.com.br/noticias/banco-do-brasil-ia-whatsapp/)
  - Banco Macro: the agent suggests routine payments for one-click approval. — [Infobae](https://www.infobae.com/economia/2026/05/22/una-app-diferente-para-cada-cliente-y-algoritmos-que-negocian-creditos-como-cambian-los-bancos-con-la-llegada-de-la-ia/)
  - **Risk:** proactive WhatsApp messages are mimicked by scammers ("falsos asesores"). Banks rely on verified-badge numbers and "never ask for credentials" rules. — [El Universal CO](https://www.eluniversal.com.co/colombia/2025/07/21/asi-operan-los-falsos-asesores-de-bancolombia-que-estafan-por-whatsapp/); [Bancolombia](https://www.bancolombia.com/acerca-de/sala-prensa/noticias/productos-servicios/como-reconocer-tabot-oficial)
- **Voice-first:**
  - BBVA México Blue: 63M calls a year; IVR abandonment of about 50% before; 30 s routing; 5% error or hallucination rate; app-originated calls to authenticate. — [DPL News](https://dplnews.com/bbva-mexico-asistente-ia-generativa-tiempos-atencion-30-segundos/)
  - Wells Fargo: voice or text, with speech transcribed and PII-scrubbed before the LLM. — [VentureBeat](https://venturebeat.com/ai/wells-fargos-ai-assistant-just-crossed-245-million-interactions-with-zero-humans-in-the-loop-and-zero-pii-to-the-llm)
  - CBA voice-bot: call volumes rose and 45 job cuts were reversed. — [ABC](https://www.abc.net.au/news/2025-08-21/cba-backtracks-on-ai-job-cuts-as-chatbot-lifts-call-volumes/105679492)
  - Voiceprint authentication is "fully defeated" by AI, per Altman at the Fed. — [Fortune](https://fortune.com/2025/07/24/sam-altman-fraud-crisis-ai-voice-mimicking-federal-reserve/)
  - Voice AI collections agents are proliferating in MX and CO (vendors), under contact rules (Ley 2300; CONDUSEF REDECO). [vendor] — [Dapta](https://dapta.ai/es/blog-posts/agentes-de-voz-con-ia-para-cobranza/); [Colombia Fintech](https://colombiafintech.co/2026/01/08/inteligencia-artificial-al-servicio-de-las-cobranzas-una-fintech-colombiana-que-busca-transformar-la-recuperacion-de-cartera-en-latinoamerica/)
- **Human-in-the-loop, copilot + handoff:**
  - NatWest: 70k+ hours saved with call summaries. — [Computer Weekly (search summary)](https://www.computerweekly.com/news/366639140/NatWest-hails-progress-after-12bn-spent-on-tech-last-year-but-true-AI-transformation-to-come)
  - Monzo: 100% human review at the start, then sampling reduced as confidence grew. — [Conversational AI News](https://www.conversationalainews.com/how-monzo-bank-built-their-own-ai-agent-for-live-customer-support-without-losing-control/)
  - Klarna: guaranteed human option; humans for disputes, fraud and hardship. [secondary for the dispute/fraud/hardship detail] — [search summary citing Klarna coverage](https://www.fintechweekly.com/magazine/articles/klarna-hires-customer-service-after-ai-pivot); [CX Dive](https://www.customerexperiencedive.com/news/klarna-reinvests-human-talent-customer-service-AI-chatbot/747586/)
  - Nequi: immediate escalation without barriers. — [El Colombiano](https://www.elcolombiano.com/tecnologia/nequi-inteligencia-artificial-credito-atencion-cliente-machine-learning-colombia-NF39695697)
  - Gartner: 87% say a human option is essential; avoid a mandatory AI-first step. — [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-08-04-gartner-survey-finds-87-percent-of-customers-say-companies-using-genai-for-customer-service-must-provide-access-to-a-human-agent0)
  - Brazil SAC decree: human phone channel for at least 8 h/day. — [Evolux](https://evolux.net.br/novo-decreto-do-sac-entenda-o-que-muda/)

### Inferences
- The strongest "AI-first but safe" design, as evidenced, is:
  1. Proactive outbound on WhatsApp from a verified identity.
  2. Narrow autonomous actions with caps and step-up authentication in the app.
  3. A copilot for the human who receives the handoff, with the full context passed so the customer isn't asked to repeat themselves.
  4. Explicit triggers for disputes, complaints, vulnerability and scam coaching that force escalation.
- Voice is differentiated for a hackathon but carries the most risk (CBA volumes, deepfakes). Framing voice as **app-authenticated** (as BBVA México does) rather than voiceprint-authenticated avoids the Altman critique.

### Gaps
- There is no public, audited CSAT or containment comparison between voice agents and chat agents in LATAM banks.
- There is no published evidence of outbound *voice* AI (as opposed to WhatsApp text) used by LATAM banks for fraud confirmation.
- There is no data on audio-message (WhatsApp voice note) share in LATAM banking conversations. Nubank and Mercado Pago accept audio, but the volume split is undisclosed.
