# What Wins Factored Datathons/Hackathons and Comparable AI-Agent Hackathons (judging, past winners, pitch)

Research date: 2026-09-29. Scope: 2022–2026. Items marked "(search-summary only)" came from a search engine's result summary, not from a page I fetched. Treat them as weaker evidence.

## Past Factored datathons/hackathons: themes, datasets, winners, rubrics

### Takeaway
Factored ran datathons in 2023 (Amazon product reviews) and 2024 (GDELT global-events data). I found no 2025 edition. The only publicly named winner is "Paisa Genious" (2023, $5,000). The entries that are documented, including the winner, share one pattern: a full data product with a lakehouse/medallion pipeline (batch plus streaming), ML models, and a deployed dashboard or web app. No official judging rubric or judge write-up from past editions is public.

### Cited Findings
- **2023 edition:** "united 500 participants and over 1400 visitors from 52 countries across Latin America." Teams worked on Amazon product reviews to build "end-to-end data solutions." The top team, **Paisa Genious**, won the **$5,000** prize. — [Factored Datathon 2024 site (now 301-redirects to the 2026 hackathon page; text seen via search index)](https://datathon.factored.ai/). Note: "52 countries across Latin America" can't be literally true because Latin America has far fewer countries. The count probably covers all countries participants came from.
- **Paisa Genious (2023 winner) solution site:** lists team members Cristina Gomez and Daverson Arenas.
  - Built a **Lakehouse platform with a multi-hop medallion pattern**, sold on scalability, cost and unified BI+ML.
  - Three analytic capabilities: historical analysis, **real-time analytics**, and **sentiment analysis**.
  - Interactive dashboards were deployed on **AWS Amplify**.
  - The site itself doesn't say it won.
  - [PaisaGenious solution site](https://main.dpnxkh6elbeqw.amplifyapp.com/)
- **Another 2023 entry ("Datapalooza"; placement unknown):**
  - Semantic product search (Sentence Transformers + Pinecone).
  - **Real-time analytics on streaming data from "Factored EventHub"**, which implies the 2023 challenge supplied a live stream.
  - Graph analysis (degree/betweenness centrality), a deployed Streamlit dashboard, batch + streaming pipelines, and infrastructure-as-code.
  - [GitHub – Juanchobanano/factored-datathon-2023-datapalooza](https://github.com/Juanchobanano/factored-datathon-2023-datapalooza)
- Other public 2023 repos exist, but I didn't review them: [juadavard/factored-datathon-2023](https://github.com/juadavard/factored-datathon-2023), [jess197/factored-datathon-2023-bifrost-analytics](https://github.com/jess197/factored-datathon-2023-bifrost-analytics).
- **2024 edition (second edition):** the challenge was to "uncover critical insights from global events to allow for early intervention and strategic planning" using the **GDELT** dataset. It ran online, and registration closed Aug 12, 2024. — [datathon.factored.ai (search-summary only)](https://datathon.factored.ai/)
- **2024 entry "LatamFusion" (placement not stated in the repo):**
  - Streaming via Azure Functions plus batch crawlers into an **Azure Databricks medallion (Bronze→Silver→Gold)** pipeline.
  - Two **RandomForestRegressor** models tuned with GridSearch forecast GDELT Tone and GoldsteinScale per country.
  - Deployed web app with time-series forecasts, world maps and **automated alert thresholds**.
  - Four-person multinational LATAM team.
  - [GitHub – hucodelab/factored-datathon-2024-LatamFusion](https://github.com/hucodelab/factored-datathon-2024-LatamFusion)
- **2023 judging criteria, possibly** "problem understanding, data analysis and modeling, and presentation skills." — [datathon.factored.ai (search-summary only; not verified on a fetched page)](https://datathon.factored.ai/)
- **Organizer context:** Factored was "conceived in Palo Alto, California in 2019 by Andrew Ng" and a team of AI researchers/educators/engineers. — [datathon.factored.ai (search-summary only)](https://datathon.factored.ai/)
- **Recruiting angle:** Factored's LinkedIn page mentions a past hackathon winner who now works at Factored, and it pitches the 2026 event to "elite engineers across LATAM." — [Factored on LinkedIn](https://www.linkedin.com/company/factoredai)
- **No 2025 edition found:** searches for "Factored Datathon 2025" returned only the 2024 site and unrelated datathons. — [search results incl. datathon.factored.ai](https://datathon.factored.ai/)

### Inferences
- Every documented Factored entry from 2023–2024 was an end-to-end data product: ingestion (often streaming), medallion lakehouse, a classical ML model, and a deployed dashboard. The 2026 brief is "AI-first/agentic," but it keeps separate Data Engineering, ML and Data Analytics dimensions. A pure chatbot with no pipeline, no trained/evaluated model and no analytics view would likely score low on three of the five dimensions.
- Factored is a staffing/engineering firm, and a past winner was hired. Judges (likely Factored engineers, unconfirmed) will probably read submissions as a proxy for hiring. Signals of engineering judgment should therefore carry weight: clean repo, reproducibility, explicit trade-offs, and tests.

### Gaps
- I found no official list of 2023 2nd/3rd place or of any 2024 winners (the site now redirects). LinkedIn posts announcing winners weren't retrievable, and the Wayback Machine was blocked for this fetcher.
- I found no published judging rubric with weights and no judge write-ups for any past Factored edition.
- I couldn't confirm whether LatamFusion or Datapalooza placed.

## The 2026 edition's stated evaluation criteria (public sources)

### Takeaway
The public page names five judged dimensions with no weights: Technical Judgment, AI Engineering, Data Engineering, Machine Learning and Data Analytics. It adds an explicit "Quality Over Quantity. You don't need to maximize every dimension" principle. The brief stresses production thinking (privacy, explainability, fairness, reliability, scalability) and explicit trade-offs. The ML dimension names **baselines** directly. The team's copy says "First and foremost our solution should work"; that line isn't on the public page, but the page asks for "a working link."

### Cited Findings
- **Timeline:**
  - Registration Sep 1–24.
  - **Challenge live Sep 25 – Oct 5** (10 days).
  - **Expert Evaluation Oct 6–15.**
  - **Finalists & Awards Oct 15–16.**
  - [Factored AI & Data Hackathon 2026](https://www.factored.ai/careers/ai-data-hackathon)
- **Challenge text (verbatim):** "Build an AI-first customer service system for a real-world banking environment. Design a solution that can understand complex customer interactions, work securely with data and tools, automate workflows, and involve human agents when needed." — [Factored hackathon page](https://www.factored.ai/careers/ai-data-hackathon)
- **Scope (verbatim):** "Choose one focused workflow such as account/payment inquiries, card support, transaction disputes, or credit-product information and eligibility." — [Factored hackathon page](https://www.factored.ai/careers/ai-data-hackathon)
- **Production framing:** "Think beyond the demo. Design for production, considering privacy, explainability, fairness, reliability, and scalability." The page also asks teams to make trade-offs explicit across **autonomy, accuracy, latency, cost, and human oversight**. — [Factored hackathon page](https://www.factored.ai/careers/ai-data-hackathon)
- **FAQ:** the system should focus on one workflow and demonstrate **understanding, decision-making, action, verification, and escalation**. "Your prototype should demonstrate customer-service interactions in both Spanish and Portuguese." The event is technology-agnostic ("languages, frameworks, models, cloud platforms, and tools"), and solo entry is allowed. — [Factored hackathon page](https://www.factored.ai/careers/ai-data-hackathon)
- **Data:** "Leverage data from enterprises like Fortune 500's" / "Solve an issue Fortune 500 enterprises face every day." Materials include a Problem Statement, Data Dictionary and Dataset Summary. — [Factored hackathon page](https://www.factored.ai/careers/ai-data-hackathon)
- **Evaluation dimensions (exact descriptions, no weights):**
  - **Technical Judgment:** "Architecture, trade-offs, reliability, safety, and production readiness."
  - **AI Engineering:** "Backend, frontend, system integration, and deployment."
  - **Data Engineering:** "Data quality, pipelines, preparation, and reproducibility."
  - **Machine Learning:** "Modeling approach, evaluation, baselines, and performance."
  - **Data Analytics:** "Metrics, insights, visualization, and decision support."
  - Principle: "Quality Over Quantity. You don't need to maximize every dimension."
  - [Factored hackathon page](https://www.factored.ai/careers/ai-data-hackathon)
- **Deliverables:**
  - Public GitHub repo named `factored-hackathon-2026-[your-team-name]`.
  - Deployed solution: "Share a working link to your tool."
  - **4–6 slides** on "approach, results, and technical decisions."
  - **Video pitch** that demonstrates the working solution and explains core architectural decisions. The page gives no video length.
  - Submit by email to hackathon.admin@factored.ai.
  - [Factored hackathon page](https://www.factored.ai/careers/ai-data-hackathon)
- **Prizes:** $10,000 total, per Factored's LinkedIn. — [Factored on LinkedIn](https://www.linkedin.com/company/factoredai). A search summary gives the split as $6,000 / $3,000 / $1,000, but I couldn't confirm it on the fetched page. — [Factored hackathon page (search-summary only)](https://www.factored.ai/careers/ai-data-hackathon)
- **Search-engine wording I couldn't find on the page:** "Judging is based on engineering judgment and production readiness, including architecture quality, reliability under real conditions, reproducibility, data quality, and business reasoning." This may be meta text or an earlier version of the page. — [Factored hackathon page (search-summary only)](https://www.factored.ai/careers/ai-data-hackathon)
- **Competitor landscape (public repos only):**
  - **23** public repos matched `factored-hackathon-2026 in:name` on 2026-09-29. With about 180 teams, most repos are still private or not yet created, so this sample is small and biased. — [GitHub repo search](https://github.com/search?q=factored-hackathon-2026+in%3Aname&type=repositories)
  - Workflows they've announced:
    - Transaction disputes ([fabian-abarca](https://github.com/FabsSWD/factored-hackathon-2026-fabian-abarca), [sentinel-engine](https://github.com/rdorta27/factored-hackathon-2026-sentinel-engine)).
    - Unrecognized charges, "detección proactiva e inteligente de cargos no reconocidos" ([sol](https://github.com/gilbertoesp/factored-hackathon-2026-sol)).
    - Credit eligibility ([noema](https://github.com/EduardoLoz12/factored-hackathon-2026-noema), [aureliano](https://github.com/nicogonzalezb/factored-hackathon-2026-aureliano)).
    - Segmentation + anomaly detection ([TM](https://github.com/algirldos/factored-hackathon-2026--TM-)).
    - A bronze/silver/gold pipeline with data-quality contracts ([Arturo-GA](https://github.com/Arturo-GA/Hackathon-Factored)).
- **NOEMA's design:**
  - "The LLM conversa; un motor de reglas versionado y modelos entrenados deciden."
  - Rules: all numbers come from DB queries and are checked by a "GroundingChecker." Eligibility comes from a versioned YAML policy engine. All writes are read back before the customer confirms.
  - Escalations are **schema-validated objects** (verified facts, actions taken, open questions), not free-text transcripts.
  - The eval harness compares **baseline vs tools vs tools+SCM**, and hallucination is measured as a rate on synthetic ground truth.
  - Two MLflow models (default risk, payment capacity) plus a baseline.
  - [GitHub – EduardoLoz12/factored-hackathon-2026-noema](https://github.com/EduardoLoz12/factored-hackathon-2026-noema)
- **NOEMA's data audit:**
  - "Row counts differ in 9 of 13 tables (23,495,188 actual vs ~19 M documented)."
  - Enums don't match the documentation.
  - Zero duplicate rows, although the documentation promised 2%.
  - Call transcripts are unsuitable: "only two unique templates across 794 rows."
  - [GitHub – noema](https://github.com/EduardoLoz12/factored-hackathon-2026-noema)
  - Sentinel Engine likewise describes 13 LATAM Bank tables with about 19M records. — [GitHub – sentinel-engine](https://github.com/rdorta27/factored-hackathon-2026-sentinel-engine)
- **Other competitors' designs:**
  - fabian-abarca: "Deterministic policy engine, calibrated decision layer, and LLM conversation in Spanish and Portuguese, with verified actions and structured human handoff." It also has a documented EDA spike on "data-label validity" for choosing the workflow and escalation labels. — [GitHub – fabian-abarca](https://github.com/FabsSWD/factored-hackathon-2026-fabian-abarca)
  - Sentinel Engine: "AI understands; code verifies and executes." It uses a Delta lakehouse (DuckDB locally, Azure Databricks in production) and tracked progress at 1 of 57 requirements done when I fetched it. — [GitHub – sentinel-engine](https://github.com/rdorta27/factored-hackathon-2026-sentinel-engine)

### Inferences
- Beyond the team's copy, the public criteria add a separate **Technical Judgment** dimension (architecture, trade-offs, reliability, **safety**, production readiness). They also name **baselines** (ML), **reproducibility** (DE) and **decision support** (Analytics). The submission should make each of these visible (see the table sketch below).
- The strongest visible competitors already use the same pattern: "LLM talks; deterministic code/rules/models decide; writes are verified; handoff is structured." This is likely **table stakes** among top-20 contenders, not a differentiator. Differentiation probably has to come from:
  - (a) a deployed link that reliably works in ES and PT;
  - (b) a quantified evaluation against a named baseline (e.g., LLM-only vs tool-grounded vs full system), with numbers on the slides;
  - (c) a data-quality audit plus business insights from the supplied dataset;
  - (d) crisp, explicit trade-off statements (autonomy/accuracy/latency/cost/oversight).
- Transaction disputes and credit eligibility already have two or three visible teams each. That's a small sample, but it suggests these are crowded choices. A crowded workflow isn't disqualifying. It does raise the bar for a distinctive angle.
- The dataset discrepancies other teams found (row counts, enums, missing duplicates, templated transcripts) will probably be found by many strong teams. Documenting them, plus how the pipeline handles them, is cheap evidence for the "Data quality" criterion. Leaving them out may look like a gap next to competitors.
- The "Expert Evaluation" window is 10 days, for about 180 teams if the team's count is right. Each submission probably gets limited reviewer time, likely in a screen-then-finalists format given the separate "Finalists" stage. README clarity, the first 60–90 seconds of the video, and whether the link works on first click are likely decisive filters.
- A mapping from criteria to evidence (inference; a template, not from a source):

| Dimension | Evidence judges can check quickly |
|---|---|
| Technical Judgment | Architecture diagram + trade-off table (autonomy/accuracy/latency/cost/oversight) + safety controls (grounding, PII redaction, write verification, escalation rules) |
| AI Engineering | Deployed URL, ES+PT flows, tool calls visible in a trace/log panel, IaC/one-command deploy |
| Data Engineering | Pipeline diagram (raw→clean→features), data-quality report with concrete discrepancies found, reproducible scripts |
| Machine Learning | Model/approach choice, eval set, **baseline vs system** metrics table, error analysis, experiment tracking |
| Data Analytics | 2–3 dataset insights that motivated the workflow choice + an ops/decision dashboard (e.g., containment rate, escalation reasons) |

### Gaps
- The public page gives no weights, judge names, video length or finalist format. I also couldn't find the team's quoted line "First and foremost our solution should work"; it may come from the private Problem Statement or the Slack channel.
- I couldn't confirm the "~180 teams / ~750 participants" figures from any public source.
- The prize split ($6k/$3k/$1k) and the "business reasoning" wording appear only in search summaries.

## Patterns of winning submissions in comparable AI-agent/LLM hackathons (2024–2026)

### Takeaway
Big agent hackathons weight technical execution heavily: 50% at both AWS and Google ADK. They screen first with a pass/fail viability check, require a deployed or working demo plus an architecture diagram, and cap video review at about 3 minutes. Judges and winners keep praising the same things: narrow scope executed end to end, a working demo within the first 90 seconds, measured evaluation with visible failures, human hand-off or fallback paths, and honesty about limitations. Strong teams lose on over-scoping, confusing demos and criteria misalignment. Finance and regulated workflows (claims, tax, fraud triage, compliance, trading analysis) show up often among winners.

### Cited Findings
- **AWS AI Agent Global Hackathon (Sept–Oct 2025):**
  - Weights: **Technical Execution 50%** ("architecture quality, reproducibility"), Potential Value/Impact 20%, Creativity 10%, Functionality 10% (agent performance and scalability), Demo Presentation 10%.
  - Stage one is a **pass/fail viability** check.
  - Required: public repo, **architecture diagram**, **deployed URL**, and a video of "around (3) minutes. Judges are not required to watch beyond three minutes" that shows the project functioning.
  - [AWS AI Agent Global Hackathon – Rules](https://aws-agent-hackathon.devpost.com/rules)
- **AWS winners** include:
  - AegisAgent (multi-agent insurance-claim review).
  - Province (AI tax filing that extracts W2/1099 data).
  - A "multi-agent fraud alert triage system" that reduces false positives (AgentCore + Bedrock).
  - Compliance Guardian ("detects violations before they become liabilities").
  - Oratio (Nova Sonic voice agents).
  - Drishti (accessibility navigation).
  - [AWS AI Agent Global Hackathon – Project gallery](https://aws-agent-hackathon.devpost.com/project-gallery)
- **Google ADK Hackathon (2025):**
  - **Technical Implementation 50%** ("Is the code clean, efficient, and well-documented?"), Innovation 30%, **Demo & Documentation 20%** ("Is the problem clearly defined…").
  - Each criterion is scored 1–5.
  - An architecture diagram is required.
  - "If it is longer than 3 minutes, only the first 3 minutes will be evaluated."
  - Stage one is pass/fail.
  - [Google Cloud ADK Hackathon – Rules](https://googlecloudmultiagents.devpost.com/rules)
- **ADK results:**
  - 476 submissions from 10,432 participants.
  - Grand prize ($15,000): **TradeSage AI**, a multi-agent financial analysis platform for evaluating trading hypotheses.
  - LATAM regional winner: SalesShortcut.
  - [Google Cloud Tech on X (search-summary only)](https://x.com/GoogleCloudTech/status/1953586166646689998)
- **Microsoft AI Agents Hackathon 2025:**
  - 570 submissions, 18,000+ registered.
  - Criteria: "innovation, impact, usability, solution quality, and category alignment."
  - Best overall: **RiskWise** (supply-chain risk agents).
  - A category winner, **ModelProof**, "validates AI trustworthiness through dual-LLM consistency checks and real-time auditing for hallucinations/bias."
  - No banking or customer-service winner.
  - [Microsoft AI Agents Hackathon – Winners](https://microsoft.github.io/AI_Agents_Hackathon/winners/)
- **Agno Global Agent Hackathon:** 100+ ideas and 60+ final submissions. Judges praised the winners' "full-stack approach" and "practical, user-focused design." — [Agno – Global agent hackathon winners](https://www.agno.com/blog/global-agent-hackathon-winners)
- **Winners' advice (ODSC–Google Cloud 2025):**
  - 1st place: "You don't have to build the most advanced system; you just need to commit, execute well, and share the story behind your idea." He scaled from a single agent to multiple agents only after the core features worked.
  - 2nd place: "Don't over-engineer… build the simplest version of your idea that works… Have a story, since judges remember narratives."
  - A finalist kept each agent "laser-focused to minimize hallucination": "Scope like a surgeon. One polished feature > five half-finished ones."
  - Another finalist: "Containerize from minute one" and deploy live (Cloud Run).
  - [ODSC – Insights from the winners](https://opendatascience.com/insights-from-the-winners-of-the-2025-odsc-google-cloud-hackathon/)
- **Judges' advice (JetBrains x Codex hackathon, June 2026):**
  - "A strong project with a confusing demo loses to a simpler project that the judges understand."
  - Jono Bacon: "Say what the problem is… get your audience of judges sharing your frustration," and show something working **within 90 seconds**.
  - Avi Press: "Be very direct about what works, what doesn't, how it works, and how it could be extended."
  - Colin Lowenberg: the demo "should show what your app does in one flow," so mock or pre-fill anything that could stall.
  - Rehearse out loud and time the pitch.
  - [JetBrains – How to Win a Hackathon: Notes From the Judging Table](https://blog.jetbrains.com/ai/2026/06/how-to-win-a-hackathon-notes-from-the-judging-table/)
- **AngelHack's agent-judging playbook:**
  - Rubric: **task completion rate**, **tool-use accuracy** ("calls the right tool at the right step"), **cost per run**, **latency**, **hallucination rate**. "These are the criteria enterprise AI teams use to judge agents in production."
  - Pitfalls: vague problem statements that lead to "impressive demos over functional agents," and judges scoring "videos and vibes."
  - Winners show multi-step end-to-end workflows and **observable execution** (trace logs, objective measurement).
  - [AngelHack – How To Run An AI Agent Hackathon: A 2026 Playbook](https://angelhack.com/blog/ai-agent-hackathon/)
  - The same source (search-summary only) says the demo shouldn't depend on a flaky third-party API, a judge should understand it "in under 30 seconds," and the "aha" moment should land in the first minute.
- **Practitioner judge's checklist for AI projects (Pranjul Rathour):**
  - Ask to see the request actually go out ("a network tab, a log line, a token counter").
  - "A team with ten test questions and a note on which three failed is showing engineering maturity."
  - For wrong, slow or down models: "A confidence threshold, a fallback, a clear error message or a human hand-off all count."
  - "Some of the best projects use AI for one narrow step and plain code for the rest."
  - Red flags: claims of perfect accuracy with no test set; "The AI handles it" with no error strategy.
  - [dev.to – Judging AI hackathon projects](https://dev.to/pranjulrathour/judging-ai-hackathon-projects-what-to-check-when-every-team-says-we-used-ai-19mb)
- **The same author's general rubric (an opinion piece):**
  - Weights: problem clarity 25%, working demo/technical execution 30%, **scope judgement and honesty about limitations 20%**, pitch/Q&A 15%, feasibility 10%.
  - "A working demo of a narrow feature beats a slide deck about a broad platform every time."
  - If "the judge cannot repeat your problem back in one sentence, the rest of the pitch is noise."
  - [dev.to – What hackathon judges actually look for](https://dev.to/pranjulrathour/what-hackathon-judges-actually-look-for-a-rubric-from-both-sides-of-the-table-39o)
- **Common reasons strong teams lose:** over-scoping ("the #1 killer"), failed or confusing demos (always keep a backup and mock slow calls), messy pitches, and building something that doesn't match the judging criteria. — [JetBrains judging notes](https://blog.jetbrains.com/ai/2026/06/how-to-win-a-hackathon-notes-from-the-judging-table/); [Bizthon – Top 5 mistakes (search-summary only)](https://medium.com/@BizthonOfficial/top-5-mistakes-developers-make-at-hackathons-and-how-to-avoid-them-d7e870746da1)

### Inferences
- Factored's five dimensions map closely onto the AWS and Google rubrics, where technical execution is about 50%. Factored adds explicit DE/ML/Analytics dimensions and a "don't maximize everything" note. The winning profile is therefore probably one narrow banking workflow done at production depth, not wide coverage.
- In most hackathons, "measured evaluation with baselines" is a nice extra. Here it's written into the ML criterion ("evaluation, baselines, and performance"). A small eval set with numbers and documented failures (task completion, tool-use accuracy, grounding/hallucination rate, escalation precision/recall, latency and cost per conversation, reported for ES and PT) is likely one of the highest-leverage additions.
- Safety and trust mechanisms (grounding checks, consistency audits, confidence thresholds with human hand-off) are both a stated Factored criterion ("safety," "explainability," "fairness") and a pattern among winners (ModelProof, compliance/fraud triage). Showing one such mechanism live in the demo is likely to form a memorable "demo moment." Examples: the agent refusing to state an unverified balance, or escalating a suspicious dispute with a structured case file.
- None of the comparable winners I found was a plain Q&A chatbot. The winners automate a multi-step, regulated workflow with actions and verification. This matches Factored's "understanding, decision-making, action, verification, and escalation."

### Gaps
- I found no public banking-customer-service hackathon winner (ES/PT) with a detailed write-up to use as a direct analogue.
- The AWS AI Agent Global Hackathon gallery doesn't say which winner took first place.
- The rubric weights from practitioner blogs are one author's opinion, not an official standard.

## What a compelling ~3-minute video pitch and 4–6 slide deck look like

### Takeaway
Across Devpost, AWS, Google and judge guides, the consensus video format is:
- **≤3 minutes**; judges may stop at 3:00.
- An elevator pitch in the first seconds.
- Real working footage early (within about 90 seconds).
- One linear user journey.
- A simple architecture view.
- An explicit "what works / what we cut" honesty beat.

Decks should stay sparse (problem, solution/demo, architecture, results, limitations/next steps), not documentation. Factored adds that the slides must cover "approach, results, and technical decisions" and the video must show the working solution plus core architectural decisions.

### Cited Findings
- **Devpost video tips:**
  - Plan early (reserve 2–3 hours).
  - Write your own script with seconds allocated to intro, problem, components, demo and close.
  - Start with the elevator pitch "in the first few seconds."
  - Keep it simple (KISS), and don't speed up the audio or cram.
  - Ensure clear audio, set the video public, and upload early.
  - [Devpost – 6 Tips for a winning hackathon demo video](https://info.devpost.com/blog/6-tips-for-making-a-hackathon-demo-video)
  - Judges "aren't required to watch past the 3-minute mark, so lead with your best material." — [Devpost (search-summary)](https://info.devpost.com/blog/6-tips-for-making-a-hackathon-demo-video)
- **AWS rules:** the video must include "footage that shows the Project functioning," with an architecture diagram and deployed URL submitted alongside. — [AWS AI Agent Global Hackathon – Rules](https://aws-agent-hackathon.devpost.com/rules). **Google ADK rules:** only the first 3 minutes are evaluated, English or English subtitles are required, and the demo and documentation must define the problem clearly and include an architecture diagram. — [Google ADK Hackathon – Rules](https://googlecloudmultiagents.devpost.com/rules)
- **A 3-minute, 7-slide template (about 30 seconds per slide):**
  - (1) The person and the pain (one human, one situation).
  - (2) Why now, why us.
  - (3) What we built (one sentence, then go to the demo).
  - (4) Live demo, about 90 seconds, one user journey on real data.
  - (5) How it works: one diagram with three boxes and the one technical choice you're proud of.
  - (6) **"What we cut and why": "Judges score it higher than any feature list."**
  - (7) What happens Monday (next step and resources).
  - Cut team-intro slides, unvetted market-size stats and complex diagrams. Aim to finish at 2:40.
  - [dev.to – A hackathon pitch deck template that fits in three minutes](https://dev.to/pranjulrathour/a-hackathon-pitch-deck-template-that-fits-in-three-minutes-12l3)
- **General deck guidance:**
  - About 5–7 slides for a 3-minute pitch: problem, solution, demo, architecture/feasibility, next steps.
  - "One frequent mistake is turning slides into documentation" (code, dense diagrams, text).
  - "Spend your pitch deck on the problem and the demo."
  - [SlideModel – Hackathon presentation (search-summary only)](https://slidemodel.com/hackathon-presentation/); [TAIKAI – Hackathon pitch in 5 steps (search-summary only)](https://taikai.network/en/blog/how-to-create-a-hackathon-pitch)
- **Judges on pitch content:** lead with the problem so judges share the frustration, show one working flow early, and say plainly what works and what doesn't. — [JetBrains judging notes](https://blog.jetbrains.com/ai/2026/06/how-to-win-a-hackathon-notes-from-the-judging-table/). Winners stress that "judges remember narratives." — [ODSC winners](https://opendatascience.com/insights-from-the-winners-of-the-2025-odsc-google-cloud-hackathon/)
- **Factored's own requirements:** 4–6 slides covering "approach, results, and technical decisions," and a video that shows the working solution and explains core architectural decisions. — [Factored hackathon page](https://www.factored.ai/careers/ai-data-hackathon)

### Inferences
- **A 4–6 slide structure for Factored.** This is an inference: sources converge on it, but no Factored winner deck is public.
  1. **Problem + data evidence.** One LATAM customer, one failing interaction, and 1–2 numbers from the supplied dataset that justify the workflow choice (Data Analytics).
  2. **What we built + live link/QR.** One sentence, a screenshot of an ES and a PT conversation, and the deployed URL.
  3. **Architecture & trade-offs.** One simple diagram (LLM understands → tools/rules decide → verify → escalate), plus a small table of the autonomy/accuracy/latency/cost/oversight choices (Technical Judgment, AI Eng).
  4. **Data pipeline & quality.** Raw→clean→features, with concrete discrepancies found in the provided data and how they're handled (Data Engineering).
  5. **Results vs baseline.** An eval table covering baseline (e.g., LLM-only) vs the full system: task completion, grounding/hallucination rate, escalation accuracy, latency, cost/conversation, by language (ML).
  6. **Limitations, what we cut, next steps.** The honesty slide, plus the safety/privacy/fairness controls and the production path.
- **A 3-minute video structure** (inference):
  - **0:00–0:15:** hook (customer pain + one number).
  - **0:15–1:30:** live demo of one journey in Spanish, then a short Portuguese segment. Include a visible "trust moment": a tool trace, a refusal to invent data, or escalation with a structured case file.
  - **1:30–2:15:** architecture and one key trade-off.
  - **2:15–2:45:** eval numbers vs baseline and the data-quality findings.
  - **2:45–3:00:** limitations and the link.
  - Finish at about 2:45 so nothing important falls past 3:00.
- Evaluation is asynchronous (Oct 6–15), so the video may be the first and possibly only "demo" judges see. A pre-recorded, rehearsed demo with real footage, no mocked results, and clean audio matters more than in live-pitch events. Mocking or pre-filling non-core steps is acceptable per the judges' advice. Faking the AI's output isn't, because practitioner judges probe for real inference.

### Gaps
- Factored doesn't publish a video length or format beyond "video pitch," and the team's copy says "short." Whether finalists present live on Oct 15–16 is unknown.
- I found no public winning deck or video from any Factored edition to use as a direct model.
