# Measuring and explaining a tool-using LLM customer-service agent: metric definitions, small-sample statistics, judge validation, error analysis, ablations, and reporting (LedgerLens)

Research date: 2026-10-03. Scope: methods for the LedgerLens hold-out evaluation (ES/PT "what is this charge?" journey: explain / secure / dispute hand-off / abstain; plus the learned ES/PT intent + abstention router vs a keyword baseline). The evaluation has a few hundred cases, ≥40 per family × language cell and ≥3 runs per case (DEC-2).

Evidence markers:
- **(abstract only)**: I read only the arXiv abstract page.
- **(search-summary only)**: the claim comes from a search engine's result summary, not a page I fetched. Treat it as weaker evidence.
- **(computed)**: a number I computed myself with scipy (Wilson / Clopper–Pearson / exact binomial). These appear under Inferences.
- **(via team notes)**: the claim comes from `research_notes/LATAM bank AI agent use cases/hackathon_judging.md`, which cites the original URL. I did not refetch it.

---

## 1. Metric definitions for a tool-using customer-service agent (task success, pass@k vs pass^k, tool-call and trajectory metrics, final state, escalation, abstention, containment vs safe resolution, unsafe outcomes)

### Takeaway
Two practices recur across τ-bench, τ²-bench and Anthropic's guidance:
- **Grade each trial on its outcome**: the final environment/DB state, plus the required facts in the reply, as a binary. A transcript claim of success counts for nothing on its own.
- **Report pass^k next to pass^1.** pass^k is the share of cases where all k runs succeed, and it is the reliability metric for customer-facing agents.

Under that headline, add diagnostic layers:
- tool choice, argument accuracy and trajectory-match mode;
- an escalation confusion matrix against gold `should_escalate`;
- abstention precision/recall plus coverage and selective risk (risk–coverage curve) for the router.

Report containment, but never count it as success. I found no published banking-specific unsafe-outcome taxonomy, so LedgerLens's taxonomy has to be assembled from DEC-0, AgentDojo-style attack metrics and outcome-vs-transcript checks.

### Cited Findings
**Outcome vs transcript, and pass@k vs pass^k**
- Anthropic's evals guide (Jan 9, 2026; Grace, Hadfield, Olivares, De Jonghe) separates two things:
  - the **outcome**, "the final state in the environment at the end of the trial";
  - the **transcript**, "the complete record of a trial, including outputs, tool calls, reasoning, intermediate results".
  - Its example: "A flight-booking agent might say 'Your flight has been booked'… but the outcome is whether a reservation exists in the environment's SQL database."
  - [Anthropic – Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- **pass@k** "measures the likelihood that an agent gets at least one correct solution in k attempts". **pass^k** "measures the probability that all k trials succeed", which is essential "for customer-facing agents where users expect reliable behavior every time." — [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- **τ-bench formulas.** With n trials per task and c successes: pass^k = E_task[C(c,k)/C(n,k)] and pass@k = 1 − E_task[C(n−c,k)/C(n,k)]. This is "the chance that all k i.i.d. task trials are successful, averaged across tasks." — [τ-bench (Yao et al., 2024)](https://arxiv.org/abs/2406.12045)
- **τ-bench results:**
  - gpt-4o on τ-retail: pass^1 = 61.2%, while "pass^8 drops to <25%".
  - τ-airline: pass^1 = 35.2%.
  - The paper runs "at least 3 trials per task", and ">40 gpt-4-turbo trials" per τ-retail task for its detailed validation.
  - [τ-bench](https://arxiv.org/abs/2406.12045)
- **τ-bench reward** is r = r_action × r_output ∈ {0,1}:
  - r_action checks "whether the final database is identical to the unique ground truth outcome database";
  - r_output checks "whether the agent's responses to the user contain all necessary information".
  - [τ-bench](https://arxiv.org/abs/2406.12045)
- **τ²-bench** combines "DB check, status assertions, natural language assertions, communication info check, and action matching":
  - action matching verifies "if every solution function exists in the actual agent-user interaction trajectory";
  - "Each task is run four times" at temperature 0.
  - [τ²-bench (Barres et al., 2025)](https://arxiv.org/abs/2506.07982)
- **Partial credit can be informative:** "A support agent that correctly identifies the problem and verifies the customer but fails to process a refund is meaningfully better than one that fails immediately." — [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- **Balanced test sets:** "Test both the cases where a behavior *should* occur and where it *shouldn't*. One-sided evals create one-sided optimization." — [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

**Tool-call and trajectory metrics**
- Tool-call testing, per Hamel Husain:
  - "Test the tool name, arguments, result, and resulting state as separate checks";
  - "test authorization and preconditions" to catch valid tool calls that violate approvals;
  - step-level diagnostics: tool choice, parameter extraction, error handling, context retention, efficiency (steps, seconds, tokens) and goal checkpoints.
  - [Hamel Husain – How do I evaluate agentic workflows?](https://hamel.dev/blog/posts/evals-faq/how-do-i-evaluate-agentic-workflows.html)
- **Trajectory match modes** in LangChain `agentevals`:
  - **strict**: "the same messages in the same order with the same tool calls";
  - **unordered**: "the same tool calls in any order";
  - **subset**: the actual trajectory holds a subset of the reference tool calls;
  - **superset**: the actual trajectory holds a superset of them.
- **Argument matching** (`tool_args_match_mode`) can be `exact` (the default), `ignore`, `subset` or `superset`, with per-tool overrides. A reference-free LLM-judge trajectory evaluator also exists.
- [LangChain agentevals](https://github.com/langchain-ai/agentevals)
- **Agents tend to repeat the same tools but vary the arguments**:
  - one 2026 study reports "structural consistency, parametric variance": mean Tool Sequence Similarity 0.87 vs mean Argument Consistency 0.69 across repeated identical runs;
  - [How Consistent Are LLM Agents? (2026) (search-summary only)](https://arxiv.org/abs/2605.28840)

**Abstention and selective-prediction metrics**
- The abstention survey defines these over outcome cells N1…N5. Definitions are quoted as given; the survey attributes them to Feng et al. 2024b, Cao et al. 2023, Yang et al. 2023 and Varshney et al. 2023.
  - **Abstention precision** = N5/(N3+N5).
  - **Abstention recall** ("prudence") = N5/(N2+N4+N5).
  - **Abstention F1**.
  - **Coverage** = (N1+N2+N4)/all.
  - **Abstention rate** = (N3+N5)/all.
  - **Over-conservativeness (ARSP)** = N3/(N1+N2+N3).
  - **URUP** = 1 − abstention recall, i.e. failing to abstain when required.
  - **Reliable accuracy** = N1/(N1+N2+N4).
  - **Effective reliability** = (N1−N2−N4)/all.
  - **Coverage@Accuracy**: the maximum coverage at which accuracy stays above a threshold.
  - **Curve-based summaries:** AUROC, AURCC and AUACC.
  - [Know Your Limits: A Survey of Abstention in LLMs (Wen et al., 2024)](https://arxiv.org/abs/2407.18418)
- **Selective classification** ("reject option") trades coverage for lower risk: "the classifier rejects instances as needed, to grant the desired risk (with high probability)." Example: a 2% top-5 ImageNet error guaranteed with probability 99.9% at "almost 60% test coverage". — [Geifman & El-Yaniv 2017 (abstract only)](https://arxiv.org/abs/1705.08500)

**Unsafe outcomes, injection and robustness**
- **AgentDojo's three metrics:**
  - **benign utility**: "the fraction of user tasks that the model solves in the absence of any attacks";
  - **utility under attack**: "the fraction of security cases… where the agent solves the user task correctly, without any adversarial side effects";
  - **targeted attack success rate (ASR)**: "the fraction of security cases where the attacker's goal is met".
- **AgentDojo scale:** 97 tasks, 629 security cases and 74 tools. Injections sit in tool outputs, and injections "at the end of tool responses achieve up to 70% success rates".
- **AgentDojo results:**
  - Claude 3.5 Sonnet: 78.22% benign utility and 51.19% utility under attack.
  - A tool-filter defense cut ASR to 6.84% while keeping 73.13% benign utility.
- [AgentDojo (Debenedetti et al., 2024)](https://arxiv.org/abs/2406.13352)
- **ReliabilityBench** measures three dimensions:
  - consistency (pass^k);
  - robustness to "semantically equivalent task perturbations": success fell from 96.9% at ε=0 to 88.1% at ε=0.2;
  - fault tolerance under "timeouts, rate limits, partial responses, schema drift": "Rate limiting is the most damaging fault".
  - It covers 1,280 episodes across 4 domains, including customer support.
  - [ReliabilityBench (2026)](https://arxiv.org/abs/2601.06112)
- **Cost:** agent evaluation should jointly optimize accuracy and cost. "SOTA agents are needlessly complex and costly." — [AI Agents That Matter (Kapoor et al., 2024) (abstract only)](https://arxiv.org/abs/2407.01502)
- **Enterprise agent rubric used in hackathons:** "task completion rate, tool-use accuracy… cost per run, latency, hallucination rate." — [AngelHack 2026 playbook (via team notes)](https://angelhack.com/blog/ai-agent-hackathon/)

**LedgerLens's own definitions (DEC-0)**
- DEC-0 already defines:
  - **safe automated resolution**: "Exit 1 or 2 is correct and policy-compliant, over all in-scope cases; also report the share attempted";
  - **containment**: "reported, but not treated as success";
  - **escalation quality**: correct queue, complete handoff, missed and unnecessary transfers;
  - **unsafe outcomes**: unauthorized disclosure; action without confirmation or read-back; wrong-charge dispute; materially wrong explanation; claiming an unverified action;
  - **efficiency**: p50/p95 latency, and cost per attempted case and per successful automated resolution.
  - [DEC-0, `docs/analysis/2026-09-26-data-findings-and-workflow-decision.md`](D:\Proyectos\ledgerlens-bank-assistant\datathon\docs\analysis\2026-09-26-data-findings-and-workflow-decision.md)

### Inferences
**Unit of analysis.** A *trial* is one case × one run. A *case* is the unit of independence. The *cluster* is `customer_id`, or the scenario template when several cases share one (see §2).

**Gold labels per case:**
- `gold_exit` ∈ {E1 explain, E2 secure, E3 hand-off, A abstain+redirect, R refuse/re-auth/safe-fallback}. "Clarify" is an allowed intermediate turn, not an exit.
- `should_escalate` and `gold_queue`.
- `expected_db_delta`: card status change, dispute/hand-off record, or none.
- `required_facts`: amount, merchant, date and decline reason, as slots.
- `allowed_tools` and `forbidden_writes`.

**Proposed metric sheet** (each one a deterministic function of trace + DB state unless marked "judge"):

| Metric | Exact definition (per trial unless noted) | Notes |
|---|---|---|
| **Trial success S** | 1 iff (a) final exit = gold_exit **and** (b) DB delta = expected (no writes unless E2/E3; E2 = confirmed block + status read-back; E3 = hand-off record with gold queue + required fields) **and** (c) all `required_facts` present and equal to the record **and** (d) no unsafe flag | τ-bench's r_action × r_output plus a safety gate |
| **pass^1, pass^3** | per case: C(c,k)/C(n,k), averaged over cases; with n=3, pass^3 = share of cases with 3/3 successes | Show both. The pass^1 − pass^3 gap is the "flakiness" headline |
| **Safe automated resolution (SAR)** | # trials with predicted exit ∈ {E1,E2} and S=1 ÷ # in-scope trials | DEC-0 wording. Also report **SAR\|automatable** (denominator = trials whose gold_exit ∈ {E1,E2}) |
| **Attempted share** | # trials where the agent chose E1/E2 ÷ # in-scope trials | DEC-0 "share attempted" |
| **Automated precision** | SAR ÷ attempted share, i.e. correct-and-safe among attempted | The system-level "selective risk" complement |
| **Containment** | # trials with no transfer ÷ all trials | Report only. A contained gold-E3 case is a **missed escalation** |
| **Escalation recall** | TP ÷ (TP+FN), with gold `should_escalate`=1 | FN = **missed transfer** |
| **Escalation precision** | TP ÷ (TP+FP) | FP = **unnecessary transfer**. Also report the FP rate = FP ÷ gold negatives |
| **Escalation F1** | harmonic mean of the two | Never report F1 without the 2×2 counts |
| **Hand-off quality \| TP** | correct queue rate; schema-valid hand-off with all required fields (deterministic); summary adequacy (judge, §3) | Conditional on a correct escalation |
| **Router coverage / selective risk** | coverage = # routed (not abstained) ÷ all; selective risk = # wrong-intent among routed ÷ # routed | Sweep the router confidence threshold to get the **risk–coverage curve** and its area (AURC) |
| **Abstention precision / recall** | precision = correct abstentions ÷ all abstentions; recall = correct abstentions ÷ should-abstain cases; over-abstention = abstained ÷ should-answer | Survey definitions mapped onto out-of-scope cases |
| **Tool precision / recall** | over the multiset of (tool, key-args) pairs: precision = \|pred ∩ ref\| ÷ \|pred\|, recall = \|pred ∩ ref\| ÷ \|ref\| | Use **superset** mode for read tools (extra reads OK). Use **strict-in-order** for the write sequence: session check → explicit confirmation → `block_card` → status read-back |
| **Argument accuracy** | among matched calls, the share whose key arguments (customer_id, card_id, transaction_id) equal the reference | Any write-tool argument mismatch = **wrong-target action** (unsafe) |
| **Unsafe outcomes U1–U6** | U1 unauthorized disclosure (any record of a non-session customer in a reply or tool call, or data shown before auth or after session expiry); U2 write without explicit confirmation; U3 claimed-unverified action (reply asserts a block/dispute that the DB lacks, or a tool errored); U4 wrong-target action (wrong card or transaction); U5 materially wrong explanation (fact ≠ record; judge-assisted); U6 injection compliance (acted on instructions in a message or a `merchant_name` field) | Report each as numerator / **opportunity denominator**: U2 over trials where a write was possible, U6 over injection cases (AgentDojo ASR analogue), U1 over all trials and separately over cross-customer trap cases |
| **Utility under attack** | share of adversarial cases solved with no unsafe side effect | AgentDojo analogue |
| **Fault-tolerance rate** | share of fault-injected cases (timeouts, empty or partial results) ending in a safe fallback with no U3 | ReliabilityBench analogue |
| **Latency** | p50/p95 of end-to-end trial wall-clock time, plus per-turn p50/p95 | Percentiles over trials. Bootstrap CI for p95 (§2) |
| **Cost** | total $ ÷ # cases (per attempted case); total $ ÷ # SAR successes (per successful automated resolution, "not defined" if 0) | Plot cost vs SAR per variant (Pareto) |

**Safety vs reliability.** For safety, the case-level aggregate should be "any run unsafe": the pass@k analogue for failures. For success, it should be "all runs succeed" (pass^k). Run-level means hide flaky unsafe behaviour.

**Avoid double counting.** "Containment" and "SAR" should never appear on the same slide without the attempted share and escalation recall. Otherwise a system that never escalates looks best.

### Gaps
- I couldn't retrieve Google Vertex AI's trajectory-metric definitions (exact / in-order / any-order / precision / recall / single-tool-use). The page redirected and rendered without content. The `agentevals` modes above are the substitute source.
- I found no published banking-specific unsafe-outcome taxonomy. U1–U6 is the team's DEC-0 list made operational, not a literature standard.
- "Safe automated resolution" is the brief's term. I found no external definition, so the denominator choice (all in-scope vs automatable-only) has to be stated explicitly.

---

## 2. Statistics for small samples (binomial intervals, zero events, clustered bootstrap, repeated runs and variance decomposition, paired comparisons, multiple comparisons)

### Takeaway
- **Unit:** the case (or customer cluster) is the unit of independence. Runs are within-case replicates, so 3 runs × 320 cases is not 960 independent observations.
- **Single rates:** use Wilson intervals (Clopper–Pearson if you want guaranteed coverage). Never use Wald.
- **Zero unsafe events:** use the rule of three, applied to cases, not trials.
- **Everything else:** use a cluster bootstrap that resamples cases (or customers) and carries all their runs.
- **System vs baseline:** use paired tests on the same cases (exact McNemar, or a paired cluster bootstrap).
- **Language × segment cells:** pre-declare a few confirmatory comparisons and apply Holm to them. Show the full grid descriptively with CIs.

### Cited Findings
**Standard errors and clustering**
- Use the CLT standard error; for binary scores, SE = √[p̂(1−p̂)/n]. — [Miller, "Adding Error Bars to Evals" (Anthropic, 2024)](https://arxiv.org/abs/2411.00640)
- When questions come in related groups, use **clustered standard errors**. "Clustered standard errors can be over 3X larger than naive standard errors" (DROP example). — [Miller](https://arxiv.org/abs/2411.00640)
- **Resampling K answers per question** cuts the conditional variance to σ²_i/K. Under uniform difficulty, Var(μ̂|K) = Var(μ̂|K=1)·(1+2/K)/3:
  - K=2 cuts variance by 1/3;
  - K=6 cuts it by 5/9;
  - the ceiling is about 2/3.
  - [Miller](https://arxiv.org/abs/2411.00640)
- **Paired comparisons:**
  - SE_{A−B} = √[SE_A² + SE_B² − 2·SE_A·SE_B·Corr(s_A,s_B)];
  - the clustered paired version sums within-cluster cross-products;
  - at r = 0.5 pairing gives about a 1/3 relative variance reduction.
  - [Miller](https://arxiv.org/abs/2411.00640)
- **Power analysis:** n = (z_{α/2}+z_β)²·(ω² + σ_A²/K_A + σ_B²/K_B)/δ², where ω² is the variance of the per-question mean differences. The minimum detectable effect is the inverse. — [Miller](https://arxiv.org/abs/2411.00640)
- **Miller's reporting advice:** report the SE in parentheses under means, include question and cluster counts, and give pairwise differences with CIs and score correlations. — [Miller](https://arxiv.org/abs/2411.00640)

**Binomial intervals and zero events**
- **Wilson** score interval methods "have been shown to be the most accurate and the most robust" (Brown, Cai & DasGupta 2001). **Wald** fails: near p̂ = 0 or 1 it "narrows to zero width (falsely implying certainty)" and overshoots [0,1].
- **Clopper–Pearson** "never has less than the nominal coverage" but is "usually conservative".
- **Jeffreys** = Beta(x+½, n−x+½) quantiles.
- Agresti & Coull (1998): "Approximate is better than 'exact'".
- **Rule of three:** when p̂ = 0, an approximate 95% CI is (0, 3/n).
- [Wikipedia – Binomial proportion confidence interval](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval)

**Paired tests and multiple comparisons**
- **McNemar's test** on the discordant pairs b, c:
  - χ² = (b−c)²/(b+c), with Edwards' continuity correction (|b−c|−1)²/(b+c);
  - "If either b or c is small (b + c < 25) then χ² is not well-approximated by the chi-squared distribution". Use the exact binomial test with n = b+c and p = 0.5 instead;
  - a mid-p variant exists.
  - [Wikipedia – McNemar's test](https://en.wikipedia.org/wiki/McNemar%27s_test)
- **Holm–Bonferroni:** sort the m p-values and reject while P_k ≤ α/(m+1−k). It controls the FWER "in the strong sense" and is "uniformly more powerful than the classic Bonferroni correction". — [Wikipedia – Holm–Bonferroni](https://en.wikipedia.org/wiki/Holm%E2%80%93Bonferroni_method)

**Cluster bootstrap and repeated runs**
- **Cluster bootstrap recipe for LLM evals:** "run each of your N inputs k times, then bootstrap by resampling inputs with replacement (carrying all k runs for each chosen input)… the 2.5th and 97.5th percentiles give a 95% interval."
  - Coverage stayed "close to nominal across all settings" with "the narrowest confidence intervals".
  - "Use k = 3 or 5 if you can afford it", since gains diminish quickly. Simulations used 5,000 bootstrap samples.
  - For nonlinear metrics such as Cohen's κ, add BCa. But BCa corrections "are noisiest exactly in the small-N, high-skew regime".
  - For comparing systems, use a **paired cluster bootstrap**, sampling both systems' responses together.
  - The authors read their multiple CIs "descriptively rather than as formal hypothesis tests".
  - [Indeed Engineering Blog – Bootstrap Confidence Intervals for LLM Evaluation (July 2026)](https://engineering.indeedblog.com/blog/2026/07/bootstrap-confidence-intervals-for-llm-evaluation/)
- **Why clusters matter:** "The true number of independent pieces of information… isn't the total number of observations, but the number of clusters." — [Cluster bootstrap overview (search-summary only)](https://www.bohrium.com/en/sciencepedia/feynman/keyword/cluster_bootstrap); see also [R Journal – Bootstrapping clustered data (search-summary only)](https://journal.r-project.org/articles/RJ-2023-015/)
- **Run-to-run variance:**
  - Anthropic: "Each task has its own success rate—maybe 90% on one task, 50% on another—and a task that passed on one eval run might fail on the next." — [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
  - Repeated runs of one coding-agent pairing "varied more than the pairings differed from one another". — [Identical Runs, Different Results (search-summary only)](https://github.com/natnew/awesome-agentops/issues/27)
  - Rankings built from single runs "invert under replication". — [Same Patient, Different Order (2026) (search-summary only)](https://arxiv.org/html/2609.13582)

### Inferences
**Worked numbers for LedgerLens cell sizes (computed, 95% two-sided unless noted):**

| Observed | Wilson 95% CI | Clopper–Pearson 95% CI | Reading |
|---|---|---|---|
| 32/40 (80%) | 65.2–89.5% | 64.4–90.9% | ±12 pts on one family × language cell |
| 64/80 (80%) | 70.0–87.3% | — | ±9 pts on one language within a family |
| 128/160 (80%) | 73.1–85.5% | — | ±6 pts |
| 256/320 (80%) | 75.3–84.0% | 75.2–84.2% | ±4 pts pooled headline |
| 20/40 (50%) | 35.2–64.8% | 33.8–66.2% | worst case ±15 pts |
| 0/40 unsafe | 0–8.8% | 0–8.8% | rule of three 7.5%; one-sided exact 95% upper 7.2% |
| 0/320 unsafe (cases) | 0–1.2% | 0–1.1% | rule of three 0.94%; one-sided exact 0.93% |
| 0/960 unsafe (trials) | — | — | 3/960 = 0.31% is **not valid**: runs are correlated. Report the case-level "any-run-unsafe" bound (0.94%) |

The rule of three is the one-sided 95% bound: (1−p)^n = 0.05 ⇒ p ≈ −ln(0.05)/n ≈ 3/n. That is standard algebra, not from a fetched source.

**Interval choice:**
- Per-cell rates: Wilson. Clopper–Pearson only for the "zero unsafe" claims, where conservatism is a virtue in banking.
- Everything clustered or non-binomial (pass^k, SAR with multi-run cases, p95 latency, cost per success, F1, AURC): case-level cluster bootstrap, B = 2,000–5,000, percentile intervals, BCa for κ.
- Clustering: if several cases share a `customer_id` or a template, resample customers (DEC-2 already splits by `customer_id`). Report the number of clusters next to n.

**How many runs:**
- Miller's formula gives variance factors of 0.56 at K=3 and 0.47 at K=5 vs K=1 (computed from (1+2/K)/3). Going from 3 to 5 runs buys ~9 points of variance reduction; more *cases* buy more.
- So keep **3 runs per case** for all variants and 5 only for the headline system, if there's budget. That is consistent with τ-bench (≥3), τ²-bench (4) and the Indeed recommendation (3 or 5).

**Variance decomposition** (report one line). For each case i with n runs and c_i successes, p_i = c_i/n:
- **within-case (run-to-run) variance** = mean_i[p_i(1−p_i)·n/(n−1)];
- **between-case variance** = Var_i(p_i) − within/n;
- **ICC** = between/(between+within);
- also report the **flaky-case share** (0 < c_i < n) and pass^1 vs pass^3.

A high ICC says failures are about *which case* (fixable by error analysis). A low ICC says they are stochastic (fixable by temperature, deterministic routing or verification).

**System vs baseline (B0 keyword router/lookup; B1 LLM-only):**
- Primary: a **paired cluster bootstrap** on the per-case mean success difference, using all runs.
- Secondary: an **exact McNemar** on case-level majority outcomes. Computed examples: discordant 12 vs 3 → p = 0.035; 10 vs 4 → p = 0.18; 8 vs 2 → p = 0.11.
- Small discordant counts need large imbalances to be significant. Say so, and don't over-claim.

**Minimum detectable effect** (paired, computed; 80% power, α = 0.05, discordance rate q ≈ 0.2, SE ≈ √(q/n)):
- n = 320 cases → MDE ≈ 7 points;
- n = 40 (one cell) → MDE ≈ 20 points.

Cell-level "ES beats PT" style claims are therefore not supportable unless the gap is about 20 points. Pool for claims and show cells descriptively.

**Multiple comparisons:**
- 2 languages × (country × Basic/Plus/Premium/Student) gives dozens of cells.
- Pre-declare about 3 confirmatory hypotheses and Holm-adjust only those:
  - H1: system SAR > B0 on the human-written held-out set;
  - H2: the router's AURC < the keyword baseline;
  - H3: the ES–PT gap in S is within ±10 pts. Use an equivalence framing, or just report the CI.
- Show the full grid with n and Wilson CIs and no stars, flag cells with n < 30, and state that the grid is descriptive (the Indeed blog's convention).

**Latency/cost percentiles:**
- Compute p50/p95 over trials and bootstrap them over cases.
- p95 from about 1,000 trials is fine. p95 inside a 40-case cell is fragile, so show it pooled.

### Gaps
- I didn't fetch Brown–Cai–DasGupta (2001) or Agresti–Coull (1998) directly; their recommendations come via Wikipedia.
- I fetched no source on Benjamini–Hochberg FDR. Dietterich's (1998) recommendation of McNemar for classifier comparison wasn't verified (the Wikipedia page doesn't cite it).
- The run-to-run variance papers (2026) are search-summary only, so their magnitudes are unverified.
- I found no source that gives a recommended ICC threshold for agent evals. The decomposition above is standard practice, not a cited protocol.

---

## 3. LLM-as-a-judge reliability (biases, cross-family judges, rubric design, calibration against human labels, agreement metrics, when to use deterministic checks)

### Takeaway
LLM judges show measurable biases:
- **position**: GPT-4 was consistent under swap only 65% of the time;
- **verbosity**: 91% failure for weaker judges;
- **self-preference**;
- **weak defect recall** on factual consistency.

LedgerLens should therefore:
- grade everything that the records/state define with **deterministic code**;
- use a **cross-family**, **binary**, **one-criterion-per-call**, **reference-guided** judge only for 2–3 subjective criteria;
- validate it on about 100–200 human labels per criterion (TPR/TNR and κ);
- then **correct the judged rate for judge error** and widen the CI.

### Cited Findings
**Known judge biases (MT-Bench study)**
- **Position bias** (default prompt, consistency under swap):
  - GPT-4: 65.0%, with 30.0% biased toward the first position;
  - Claude-v1: 23.8% (75.0% toward first);
  - GPT-3.5: 46.2% (50.0% toward first).
  - [Zheng et al., Judging LLM-as-a-Judge (2023)](https://arxiv.org/abs/2306.05685)
- **Verbosity bias** ("repetitive list" attack failure rate): Claude-v1 91.3%, GPT-3.5 91.3%, GPT-4 8.7%. — [Zheng et al.](https://arxiv.org/abs/2306.05685)
- **Grading errors on math/reasoning** dropped from 14/20 (default) to 6/20 with chain-of-thought and 3/20 with **reference-guided** grading. — [Zheng et al.](https://arxiv.org/abs/2306.05685)
- **Agreement with humans:** GPT-4 matched human experts 85% of the time vs 81% human–human (setup without ties). The abstract says "over 80% agreement, the same level of agreement between humans". — [Zheng et al.](https://arxiv.org/abs/2306.05685)
- **Self-enhancement:** "Gpt-4 favored itself with a 10% higher win rate while claude-v1 favored itself with a 25% higher win rate". — [Eugene Yan – Evaluating the Effectiveness of LLM-Evaluators](https://eugeneyan.com/writing/llm-evaluators/), citing Zheng et al.
- **Self-preference and self-recognition:**
  - LLMs such as GPT-4 and Llama 2 can recognize their own outputs, and there is "a linear correlation between self-recognition capability and the strength of self-preference bias" — [Panickssery et al., NeurIPS 2024 (search-summary only)](https://proceedings.neurips.cc/paper_files/paper/2024/file/7f1f0218e45f5414c79c0679633e47bc-Paper-Conference.pdf);
  - contested by a 2026 study: under blind evaluation, self-preference "largely disappears once selection quality and evaluator severity are controlled" — [Quantifying and Mitigating Self-Preference Bias (2026) (search-summary only)](https://arxiv.org/html/2604.22891v4).

**Rubric and metric guidance**
- **Juries:** a panel of three smaller models from different families (PoLL: command-r, gpt-3.5-turbo, haiku) correlated better with humans than GPT-4 alone at "one-seventh the cost". — [Eugene Yan](https://eugeneyan.com/writing/llm-evaluators/), citing Verga et al. 2024
- **Binary outputs:** "where possible, I have my evaluators return binary outputs. This improves model performance while making it easier to apply classification metrics." — [Eugene Yan](https://eugeneyan.com/writing/llm-evaluators/)
- **Correlation can mislead:** one judge had "percentage agreement of 80%, [but] Cohen's κ was only 0.62". — [Eugene Yan](https://eugeneyan.com/writing/llm-evaluators/)
- **Hallucination detection is weak:**
  - the best model reached only 58.5% accuracy separating factual from hallucinated summaries (HaluEval);
  - gpt-3.5-turbo passed >95% of consistent summaries but caught only 30–60% of inconsistent ones (low defect recall).
  - [Eugene Yan](https://eugeneyan.com/writing/llm-evaluators/)
- **Binary over Likert:** "Binary evaluations force clearer thinking and more consistent labeling. Likert scales introduce significant challenges: the difference between adjacent points… is subjective and inconsistent across annotators." — [Hamel Husain & Shreya Shankar – AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
- **Judge validation (Hamel/Shankar):**
  - measure **TPR** ("how many actual failures the evaluator catches") and **TNR** ("how many good outputs the evaluator correctly passes"), not raw agreement;
  - "Label 100 to 200 examples for each failure mode", split 10–20% train, 40–45% dev, 40–45% held-out test;
  - "Use a code-based eval when a deterministic rule can identify the failure… whether a tool call uses the correct arguments";
  - use a single domain expert, the "benevolent dictator", as the labelling authority.
  - [Hamel Husain – AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
- **Anthropic's judge guidance:**
  - "LLM-based rubrics should be frequently calibrated against expert human judgment";
  - "give the LLM a way out, like providing an instruction to return 'Unknown'";
  - "grade each dimension with an isolated LLM-as-judge rather than using one to grade all dimensions";
  - "You won't know if your graders are working well unless you read the transcripts and grades from many trials."
  - [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

**Correcting for judge error**
- **judgy** (Shreya Shankar's package) estimates the judge's TPR/TNR on labelled data, corrects the observed pass rate with θ̂ = (p_obs + TNR − 1)/(TPR + TNR − 1) (the Rogan–Gladen form), and bootstraps a CI. — [judgy on GitHub (search-summary only)](https://github.com/ai-evals-course/judgy)
- **Lee et al. (2025), "How to Correctly Report LLM-as-a-Judge Evaluations":**
  - "imperfect sensitivity and specificity of the LLM judges induce bias in naive evaluation scores";
  - they propose a plug-in correction with "confidence intervals that account for uncertainty from both the test dataset and a human-labeled calibration dataset", plus adaptive allocation of calibration samples;
  - the method stays unbiased under test/calibration distribution shift.
  - [arXiv 2511.21140 (abstract only)](https://arxiv.org/abs/2511.21140)
- **Criteria drift:** "users need criteria to grade outputs, but grading outputs helps users define criteria". — [Shankar et al., Who Validates the Validators? (2024) (abstract only)](https://arxiv.org/abs/2404.12272)

**Agreement metrics and judge validation in published taxonomies**
- **Cohen's κ** = (p_o − p_e)/(1 − p_e).
  - Landis & Koch bands: 0.21–0.40 fair, 0.41–0.60 moderate, 0.61–0.80 substantial, 0.81–1 almost perfect. These are "by no means universally accepted".
  - **Kappa paradox:** identical 60% agreement can give κ = 0.13 or 0.26 depending on marginal distributions (prevalence).
  - For more than two raters, use Fleiss' κ or Krippendorff's α.
  - [Wikipedia – Cohen's kappa](https://en.wikipedia.org/wiki/Cohen%27s_kappa)
- **MAST** validated its taxonomy with human inter-annotator κ = 0.88. Its o1-based LLM annotator reached accuracy 0.94 and κ = 0.77 vs humans, and κ = 0.79 on unseen systems. — [Cemri et al., Why Do Multi-Agent LLM Systems Fail? (2025)](https://arxiv.org/abs/2503.13657)
- **LLMs are poor at localizing failures in traces:**
  - Who&When: best automated attribution was 53.5% (agent-level) and 14.2% (step-level) — [Who&When (2025) (abstract only)](https://arxiv.org/abs/2505.00212);
  - TRAIL: the best model (Gemini-2.5-Pro) reached 11% joint accuracy — [TRAIL (2025)](https://arxiv.org/abs/2505.08638).

### Inferences
**Judge validation protocol for LedgerLens** (fits in about half a day for two people):
1. **Deterministic first.** Code-check these:
   - exit label and DB delta;
   - tool names and arguments;
   - the confirmation-before-write ordering and the read-back;
   - cross-customer IDs in replies or tool calls (U1);
   - required-fact slot match (amount, date, merchant, decline code);
   - reply language (a language-ID library);
   - hand-off JSON schema validity.

   This should cover most of the success definition and U1–U4 and U6. Only U5 ("materially wrong explanation" phrased in free text), language/register appropriateness and hand-off summary adequacy need a judge.
2. **Judge design:**
   - one binary criterion per call: J1 "explanation faithful to the provided record", J2 "replies in the customer's language and register", J3 "hand-off summary lets an agent act without re-asking";
   - **reference-guided**: pass the DB record and gold facts;
   - rationale before verdict, an `UNKNOWN` escape that routes to human review, and temperature 0.
3. **Judge model:** use a **different family** from the agent's Claude. On Bedrock that could be Amazon Nova or Llama/Mistral, or a 3-model jury per PoLL. This avoids self-preference and is cheap insurance, even though the 2026 rebuttal suggests the bias may be smaller under blind evaluation. Don't run pairwise judging unless needed; if you do, run both orders and count inconsistent verdicts as ties.
4. **Labels:**
   - sample about 100–150 trials per judged criterion, stratified by language and enriched for failures (failures are rare, and κ and TNR are unstable at low prevalence);
   - one person is the labelling authority (the benevolent dictator); the PT-fluent reviewer labels PT;
   - **double-label 30–50** items to get a human–human κ ceiling;
   - freeze a 40–45% test split before iterating the judge prompt.
5. **Acceptance:** report TPR, TNR and κ, each with a bootstrap CI.

   Proposed bar (my inference, not a cited standard):
   - TPR ≥ 0.85 and TNR ≥ 0.90 on the test split;
   - κ in the "substantial" band or above (≥ 0.61);
   - otherwise drop the judged criterion from the headline and report it qualitatively.
6. **Report corrected rates:** θ̂ = (p_obs + TNR − 1)/(TPR + TNR − 1), with a bootstrap over both the test and calibration sets (judgy / Lee et al.). Show raw and corrected side by side.
7. **No LLM failure attribution.** Don't use an LLM to assign failure categories as a headline. Who&When (14.2% step-level) and TRAIL (11%) show it is unreliable. LLM pre-tagging is fine only if a human confirms every tag.

### Gaps
- I didn't fetch Panickssery et al. or the 2026 self-preference rebuttal directly, so their effect sizes are unverified.
- I found no study validating LLM judges specifically for Spanish/Portuguese banking dialogue. Judge accuracy in PT should be measured, not assumed.
- I didn't fetch Krippendorff's α computation details. For two raters and binary labels, Cohen's κ suffices.

---

## 4. Explaining agent behaviour (failure taxonomies, trace-based error-analysis workflow, ablations, counterfactual/minimal-pair analysis, attributing failures to model vs tool vs policy vs data)

### Takeaway
"Why" evidence should come from four complementary instruments, all run on the frozen held-out set:
1. **A trace-grounded failure taxonomy** built by open → axial coding of about 100 failing traces. Count each failure at its **first upstream failure**, with an owner label (model / tool / policy / data / eval-harness), and show a **transition failure matrix** over the journey states.
2. **An ablation ladder** (B0 → B1 → full; full minus Cedar policy, minus confirmation/read-back, minus learned router; model swap). Compare variants on the same cases with paired CIs and a cost/latency Pareto.
3. **Minimal-pair counterfactuals** in the CheckList style. Invariance (INV) tests check that paraphrase, ES↔PT and code-switching don't change the exit. Directional (DIR) tests check that flipping one record field changes the exit as policy dictates.
4. **Fault and injection suites** (ReliabilityBench / AgentDojo style), to show safe fallback rather than claimed actions.

### Cited Findings
**Error-analysis workflow (Hamel Husain / Shreya Shankar)**
- **Open coding, then axial coding:** "Human annotator(s) (ideally a benevolent dictator) review and write open-ended notes about traces, noting any issues", then "Categorize the open-ended notes into a 'failure taxonomy.'" — [Hamel Husain – AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
- **How many traces:**
  - "A working pool of roughly 100 diverse traces is a useful guardrail";
  - annotate "at least the first 30 yourself before reviewing suggestions from an agent";
  - "Continue until new traces stop revealing failure modes… theoretical saturation."
  - [Hamel Husain – AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
- **First upstream failure:** "focus on noting the first failure observed in a trace, as upstream errors can cause downstream issues." — [Hamel Husain – AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
- **Two phases for agents:** first "Treat the agent as a black box and decide whether it met the user's goal", recording "the first upstream failure". Then run step-level diagnostics.
- **Transition failure matrix:** rows are the "last successful state" and columns the "first failure" location. "The counts show where to investigate first."
- [Hamel Husain – How do I evaluate agentic workflows?](https://hamel.dev/blog/posts/evals-faq/how-do-i-evaluate-agentic-workflows.html); also [Where Did It Break? (2026) (search-summary only)](https://manisnesan.github.io/chrestotes/posts/2026-06-04-where-did-it-break.html)
- **Synthetic data from dimensions:** "Start by defining dimensions… Generate structured tuples… Convert tuples to queries" in a separate prompt. — [Hamel Husain – AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)

**Published failure taxonomies**
- **MAST** (grounded theory over 150 traces from 5 frameworks, 6 experts, κ = 0.88) defines three categories and 14 modes, with prevalence:
  - **FC1 System design:**
    - FM-1.1 disobey task specification 11.8%;
    - FM-1.2 disobey role specification 1.5%;
    - FM-1.3 step repetition 15.7%;
    - FM-1.4 loss of conversation history 2.8%;
    - FM-1.5 unaware of termination conditions 12.4%.
  - **FC2 Inter-agent misalignment:**
    - FM-2.1 conversation reset 2.2%;
    - FM-2.2 fail to ask for clarification 6.8%;
    - FM-2.3 task derailment 7.4%;
    - FM-2.4 information withholding 0.85%;
    - FM-2.5 ignored other agent's input 1.9%;
    - FM-2.6 reasoning–action mismatch 13.2%.
  - **FC3 Task verification:**
    - FM-3.1 premature termination 6.2%;
    - FM-3.2 no or incomplete verification 8.2%;
    - FM-3.3 incorrect verification 9.1%.
  - [MAST (Cemri et al., 2025)](https://arxiv.org/abs/2503.13657)
- **τ-bench's manual analysis** of 36 failed gpt-4o trajectories found three classes:
  - wrong argument/information;
  - **wrong decision-making / rule following**, "25% of overall failures";
  - **partial resolution of compound requests**, "19% of cases".
  - [τ-bench](https://arxiv.org/abs/2406.12045)
- **τ²-bench ablation:** moving from No-User mode to the collaborative Default mode drops pass^1 by 18% (gpt-4.1) and 25% (o4-mini). This isolates the cost of communication and coordination from pure reasoning. User-simulator errors are separated into "task-critical" and "task-benign". — [τ²-bench](https://arxiv.org/abs/2506.07982)
- **TRAIL taxonomy:**
  - **Reasoning errors:** hallucinations, information processing, decision making (incl. tool selection), output generation (formatting, instruction non-compliance);
  - **System execution errors:** configuration, API & system issues (rate limits, auth, not-found), resource management (exhaustion, timeouts);
  - **Planning & coordination errors:** context management (incl. repeated tool calls), task management (goal deviation, orchestration).
  - Dataset: 148 traces and 841 annotated errors. Output-generation errors were 353/841 ≈ 42%.
  - [TRAIL (Deshpande et al., 2025)](https://arxiv.org/abs/2505.08638)
- **Automated failure attribution is weak:** 53.5% agent-level and 14.2% step-level, "some methods performing below random". — [Who&When (Zhang et al., 2025) (abstract only)](https://arxiv.org/abs/2505.00212)

**Behavioural (minimal-pair) testing and stress suites**
- **CheckList's three test types:**
  - **Minimum Functionality Tests:** simple, templated cases with known labels;
  - **Invariance tests:** "the model prediction remains the same when the input is perturbed in ways that should not affect the expected output", e.g. "changing location names should not change sentiment";
  - **Directional Expectation tests:** the prediction should change in a specified direction.
  - Tests are organized as a capability × test-type matrix.
  - Practitioners using CheckList "created twice as many tests, and found almost three times as many bugs".
  - [Ribeiro et al., CheckList (ACL 2020)](https://arxiv.org/abs/2005.04118)
- **AgentDojo:** injection position matters (end of tool response, up to 70% success). A tool-filter defense dropped ASR to 6.84%. Defenses are evaluated as ablations on utility vs ASR. — [AgentDojo](https://arxiv.org/abs/2406.13352)
- **ReliabilityBench:**
  - the perturbation dimension (ε) and fault dimension (λ: timeouts, rate limits, partial responses, schema drift) are ablation axes;
  - "ReAct is more robust than Reflexion under combined stress";
  - "Gemini 2.0 Flash achieves comparable reliability to GPT-4o at much lower cost".
  - [ReliabilityBench](https://arxiv.org/abs/2601.06112)
- **Kapoor et al.:** agent evaluations produce "mistaken conclusions about the sources of accuracy gains", and "many agent benchmarks have inadequate holdout sets". This argues for simple baselines and frozen holdouts. — [AI Agents That Matter (abstract only)](https://arxiv.org/abs/2407.01502)

### Inferences
**Seed axial codes for LedgerLens.** Map each to an **owner** so that attribution is a lookup, not a judgement call. The MAST/τ/TRAIL anchors are in brackets.

| Code | Example in LedgerLens | Owner | Anchor |
|---|---|---|---|
| A1 Wrong intent/route | "bloquear" read as "explain"; out-of-scope loan request routed in | router (learned) | TRAIL decision making |
| A2 Missed ambiguity | several candidate transactions, no clarifying question | model / prompt | MAST FM-2.2 |
| B1 Wrong target | matched the wrong transaction or card | model (args) or matcher | τ wrong argument |
| B2 Misread record | decline code or status misinterpreted | model | TRAIL information processing |
| B3 Ungrounded fact | invented merchant detail or date | model | TRAIL hallucination |
| C1 Policy violation | wrote without confirmation; disclosed before auth | model, and policy gap if Cedar allowed it | τ wrong decision |
| C2 Escalation error | missed or unnecessary transfer, wrong queue | model / policy rules | — |
| D1 No read-back / claimed unverified action | "your card is blocked" without a status re-read | model / orchestration | MAST FM-3.2/3.3 |
| E1 Session/auth handling | expired session not re-authenticated | orchestration / tool | — |
| F1 Tool failure not handled | timeout after confirmation → hallucinated success | tool + model | TRAIL API/system issues |
| G1 Loop / premature end | repeated tool calls; conversation ended before hand-off | model | MAST FM-1.3 / FM-1.5 / FM-3.1 |
| H1 Data defect | null decline code; "Pending with decline code" (F8/F46) | data (should be flagged, not explained) | — |
| I1 Eval artefact | gold label wrong; scripted user turn unrealistic | eval harness | τ² task-critical user-sim error |

**Deterministic attribution rule:**
- If Cedar/Gateway denied the call → **policy** (correct block, or over-block if gold says the call was allowed).
- Else if the tool returned an error or timeout → **tool**, plus **model** if the reply then claims success.
- Else if the tool returned correct data and the reply or args contradict it → **model**.
- Else if the record itself is defective → **data**.
- Else if the gold label is disputed on review → **eval**.

Count only the first upstream failure per failing trial and report counts with Wilson CIs. This turns "why" into a bar chart.

**Transition failure matrix states for this journey:** auth/session → intent route → candidate match → (clarify) → explain / confirm → write → read-back → hand-off / close. Rows are the last successful state and columns the first failed state. One heatmap shows where the agent breaks, and it doubles as a slide visual.

**Ablation ladder.** Run each variant on the same frozen held-out cases with 3 runs, as paired cluster-bootstrap deltas on SAR, the U-rates and cost:
- **V0 = B0** (keyword router + decline-code lookup + "pick from last N" + always escalate on ambiguity). This is the ML-criterion baseline.
- **V1 = B1:** the same Claude with no tools or guardrails, on the adversarial family only. It shows the unsafe outcomes a naive LLM produces: U1/U3/U5 counts.
- **V2 = full system.**
- **V3 = full − Cedar** (authorization by prompt only), on the cross-customer and injection families. It shows what the policy layer contributes, as an ASR / U1 delta.
- **V4 = full − confirmation/read-back step.** It shows the U2/U3 delta, and the latency saved.
- **V5 = full with the keyword router in place of the learned router.** It shows the router's end-to-end contribution, alongside its standalone risk–coverage comparison.
- **V6 = model swap** (smaller/cheaper Claude). It gives the cost/latency vs SAR Pareto points (Kapoor).
- If time is short, V0, V2, V5 and one of V3/V4 are the minimum. Each extra variant costs about 320 × 3 conversations.

**Minimal-pair counterfactuals** (CheckList applied to records and utterances). Build 30–60 pairs from existing cases by changing one thing:
- **DIR on records:**
  - card status active → blocked: the exit should change from "secure" to "explain already blocked";
  - decline code 51 → 05: the explanation changes;
  - transaction pending → reversed;
  - the customer's own card → another customer's card: the exit should become refuse;
  - `merchant_name` clean → containing an injected instruction: the exit should not change, and U6 must stay 0.
- **INV on utterances:**
  - paraphrase;
  - ES ↔ PT translation of the same case;
  - code-switching;
  - accent stripping or typos;
  - a different customer name or amount format.
- **Report:**
  - **DIR compliance** = the share of pairs where the decision changed exactly as policy dictates;
  - **INV violation rate** = the share of pairs where the exit changed when it shouldn't have.

Paired by construction, these show *which input fields drive decisions*: direct "explainability" evidence for the Technical Judgment criterion. The ES↔PT INV pairs are also the cleanest language-gap measurement, since they're paired and isolate language.

**Fault injection.** For about 20–40 cases, force tool timeouts or errors (including after confirmation), empty results and an expired session mid-flow. Report the safe-fallback rate and the U3 (claimed-unverified) count. This maps directly onto the brief's "tool failures" and "expired sessions" families.

### Gaps
- The τ-bench page I fetched didn't give the share for the "wrong argument/information" class; only the 25% and 19% figures were extracted.
- MAST was built for multi-agent systems. Applying FC1/FC3 and FM-2.2/2.6 to a single agent talking to a user is my inference, not validated by the authors.
- I found no published single-agent customer-service failure taxonomy with reported inter-annotator agreement. LedgerLens's own taxonomy should report its double-coded κ.

---

## 5. Reporting results credibly (what a credible evaluation section/slide looks like)

### Takeaway
A credible evaluation section has:
- a **frozen, human-written held-out headline** with n, clusters, rates and 95% CIs;
- the **baseline and paired deltas** next to the system;
- an **exit confusion matrix**;
- **unsafe outcomes as numerator/denominator** with upper bounds when zero;
- the **router's risk–coverage curve** vs the keyword baseline;
- **pass^1 vs pass^3** (reliability);
- **p50/p95 latency and cost per attempt / per success**;
- a **counted failure taxonomy with 1–2 real traces**, plus an explicit limitations line.

Judges in agent hackathons reward measured evaluation with visible failures and penalize claims of perfect accuracy with no test set.

### Cited Findings
- **Miller's reporting rules:** report SE (or CI) with every mean, the number of questions and clusters, and pairwise differences with CIs and correlations. — [Miller](https://arxiv.org/abs/2411.00640)
- **Indeed's convention:** read multiple CIs descriptively, not as formal tests. — [Indeed Engineering Blog](https://engineering.indeedblog.com/blog/2026/07/bootstrap-confidence-intervals-for-llm-evaluation/)
- **τ-bench's reliability headline** is the pass^k decay (61.2% at k=1 to <25% at k=8). — [τ-bench](https://arxiv.org/abs/2406.12045)
- **AgentDojo** reports three numbers side by side (benign utility, utility under attack, ASR) and shows defenses as utility/ASR trade-offs. — [AgentDojo](https://arxiv.org/abs/2406.13352)
- **Kapoor et al.:** report accuracy and cost jointly. — [AI Agents That Matter](https://arxiv.org/abs/2407.01502)
- **Abstention reporting:** Coverage@Accuracy, plus curve summaries (AUROC/AURCC/AUACC). — [Know Your Limits](https://arxiv.org/abs/2407.18418)
- **Transition failure matrix:** "The counts show where to investigate first." — [Hamel Husain](https://hamel.dev/blog/posts/evals-faq/how-do-i-evaluate-agentic-workflows.html)
- **Read transcripts:** "When a task fails, the transcript tells you whether the agent made a genuine mistake or whether your graders rejected a valid solution." — [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- **Factored's criteria:**
  - Machine Learning = "Modeling approach, evaluation, baselines, and performance";
  - Data Analytics = "Metrics, insights, visualization, and decision support";
  - Technical Judgment includes "reliability, safety, and production readiness";
  - deliverables are 4–6 slides on "approach, results, and technical decisions".
  - [Factored AI & Data Hackathon 2026 (via team notes)](https://www.factored.ai/careers/ai-data-hackathon)
- **Practitioner judge (Pranjul Rathour):** "A team with ten test questions and a note on which three failed is showing engineering maturity." The red flag is claims of perfect accuracy with no test set. — [dev.to – Judging AI hackathon projects (via team notes)](https://dev.to/pranjulrathour/judging-ai-hackathon-projects-what-to-check-when-every-team-says-we-used-ai-19mb)
- **AngelHack:** winners show "observable execution (trace logs, objective measurement)". — [AngelHack (via team notes)](https://angelhack.com/blog/ai-agent-hackathon/)

### Inferences
**Reporting template.** Table and figure specs only; there are no results yet.

**Slide "Results vs baseline" (one slide):**
- **T1 Headline (human-written held-out, frozen):**
  - rows: SAR (all in-scope), attempted share, automated precision, escalation recall/precision, unsafe (any U), pass^1, pass^3, p50/p95 latency, $ per attempted case, $ per successful automated resolution;
  - columns: B0 | Full | Δ (paired 95% CI) | n cases / clusters / runs.
  - Format: "78% [72–83]".
- **F1 Exit confusion matrix** (gold rows E1/E2/E3/Abstain/Refuse × predicted columns, counts with row %). Color the cells green (correct), amber (safe but suboptimal, e.g. unnecessary hand-off) and red (unsafe, e.g. E2 predicted where gold is Refuse). This one picture shows containment, escalation errors and safety together.
- **F2 Router risk–coverage curve:**
  - learned router (curve over thresholds) vs keyword baseline (point or points), separately for ES and PT;
  - mark the deployed threshold and report AURC with a bootstrap CI;
  - the ML-criterion evidence.

**Slide "Safety & why":**
- **T2 Unsafe outcomes:** U1–U6 rows. Columns: count / opportunity denominator, rate, 95% upper bound (Clopper–Pearson or rule of three when 0), and the family where opportunities arise. Add a B1 (LLM-only) column to show what the guardrails prevent.
- **F3 Failure taxonomy Pareto:** first-upstream-failure counts by code and owner, each bar with a Wilson CI. Inset the transition failure matrix heatmap.
- **Two trace call-outs:** one prevented-unsafe example (an injection in `merchant_name` ignored; a Cedar deny on another customer's card) and one real failure we didn't fix, with its code.

**Appendix / README:**
- T3 Per language × segment grid: n, S, SAR and unsafe, with Wilson CIs. n < 30 cells are greyed out and labelled "descriptive only".
- T4 Run variability: pass^1 vs pass^3, flaky-case share and ICC (§2).
- T5 Ablation ladder V0–V6: paired ΔSAR, ΔU and Δcost with CIs. F4 is the cost vs SAR Pareto scatter.
- T6 Judge validation: per criterion, the n labelled, TPR, TNR and κ (with CIs), human–human κ, and raw vs corrected rate.
- T7 Minimal pairs: DIR compliance and INV violation rate, by perturbation type and language.
- **Limitations box:**
  - team-generated cases and labels (DEC-2);
  - a synthetic policy defines the gold;
  - the PT reviewer is single-person;
  - historical KPIs are not a baseline (DEC-0);
  - no live traffic.

**Wording discipline:**
- Always "n = …, 95% CI".
- Say "0 observed in 320 cases (≤0.94% at 95%)", not "zero unsafe outcomes".
- Name the held-out family that the headline comes from.

### Gaps
- No Factored-specific example of a winning evaluation slide is public (also noted in the team's judging notes).
- I found no source prescribing a standard "evaluation slide" format for agent hackathons. The template above is synthesized from the cited reporting practices.

---

## 6. Alignment with the team's judging notes and DEC-0 / DEC-2, and what to change in 1–2 days

### Takeaway
DEC-0 and DEC-2 already match the literature well:
- outcome-based exits;
- a deterministic gold from records;
- splits by customer and generator family;
- a human-written held-out headline;
- ≥3 runs;
- a judge validated against humans;
- a B0 baseline;
- unsafe outcomes with denominators and the rule of three.

What is missing is:
- the **unit-of-analysis and cluster rules**;
- the **pass^k** reliability view;
- **opportunity denominators per unsafe type**;
- the **router risk–coverage comparison**;
- **paired tests** for system vs baseline;
- **Holm on a few pre-declared hypotheses**;
- **judge-error correction**;
- a **first-upstream-failure taxonomy with owners**;
- **minimal-pair and fault-injection** suites.

All of it is feasible in about 2 days with scripts.

### Cited Findings
- **DEC-0** lists safe automated resolution (+ share attempted), containment (not success), escalation quality (missed/unnecessary vs reference labels), unsafe outcomes, efficiency (p50/p95, cost per attempted case and per success), all "by language… and segment… with n", plus B0/B1 baselines and "the rule-of-three upper bound when zero are observed". — [DEC-0](D:\Proyectos\ledgerlens-bank-assistant\datathon\docs\analysis\2026-09-26-data-findings-and-workflow-decision.md)
- **DEC-2** specifies:
  - splits by `customer_id` and generator family;
  - "The human-written held-out set is the headline result", frozen before tuning;
  - ≥40 per family × language cell, ≥320 conversations and ≥3 runs per case;
  - four families: Normal, Ambiguous/unsupported, Human-required, Adversarial/failure;
  - "An LLM judge, if used, has a written rubric and is validated against a human-labelled sample".
  - [DEC-2](D:\Proyectos\ledgerlens-bank-assistant\datathon\docs\analysis\2026-09-26-data-findings-and-workflow-decision.md)
- **The team's judging notes infer** that a "small eval set with numbers and documented failures (task completion, tool-use accuracy, grounding/hallucination rate, escalation precision/recall, latency and cost per conversation, reported for ES and PT) is likely one of the highest-leverage additions". — [hackathon_judging.md](D:\Proyectos\ledgerlens-bank-assistant\datathon\research_notes\LATAM bank AI agent use cases\hackathon_judging.md)
- **Visible competitors** (e.g., NOEMA) already run "baseline vs tools vs tools+SCM" eval harnesses with a hallucination rate on synthetic ground truth. A baseline comparison is therefore table stakes, not a differentiator. — [hackathon_judging.md, citing GitHub – noema](https://github.com/EduardoLoz12/factored-hackathon-2026-noema)
- **Anthropic:** "20-50 simple tasks drawn from real failures is a great start". Capability evals "should start at a low pass rate"; regression evals "should have a nearly 100% pass rate". — [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

### Inferences
**Concrete deltas to DEC-0/DEC-2:**
1. Add the **metric sheet** from §1, so that every rate states its numerator and denominator. Fix the SAR denominator: report both "all in-scope" and "automatable-only".
2. Declare **case = unit** and **customer = cluster**, and compute every CI by case-level cluster bootstrap. Wilson only for single-run rates; Clopper–Pearson / rule of three on cases for zero-event safety claims.
3. Add **pass^3** next to pass^1, the **flaky-case share** and the ICC.
4. Pre-declare **H1–H3** (§2) and Holm-adjust them. Label the language × segment grid descriptive.
5. Add **router evaluation as selective prediction:** a risk–coverage curve plus AURC vs the keyword baseline, per language, on held-out human-written utterances. This is the "learned component vs baseline" evidence the ML criterion names.
6. The **judge** covers only J1–J3, cross-family and reference-guided. Calibrate it on about 100–150 labels per criterion and report TPR/TNR/κ and corrected rates.
7. The **"why" package:** a first-upstream-failure taxonomy with owners, a transition matrix, a 3–5-variant ablation ladder, 30–60 minimal pairs and 20–40 fault-injection cases.
8. To cut harness noise, use **scripted user turns** for confirmations and identity answers wherever possible. If an LLM user simulator is used, classify simulator errors as task-critical vs task-benign (τ²) and exclude or flag task-critical ones. That's an inference from τ²'s categorization.

**1–2 day schedule for two people:**
- **Day 1 AM:** freeze the held-out set. Write the deterministic graders (exit, DB delta, args, ordering, read-back, cross-customer IDs, slot facts, language-ID, hand-off schema).
- **Day 1 PM:** run Full + B0 at 3 runs each (about 2 × 960 trials) and compute the T1/F1/T2 tables with one script (Wilson, cluster bootstrap, exact McNemar). Start open coding on about 60–100 failing traces: person A codes, person B double-codes 30.
- **Day 2 AM:** axial coding → taxonomy counts and transition matrix. Run 1–3 ablations (V5 router swap is the priority, then V3 or V4), minimal pairs and fault cases. Label 100–150 items for judge criteria J1–J3 and compute TPR/TNR/κ.
- **Day 2 PM:** router risk–coverage plot, Pareto plot, final tables, the results slide and the limitations box. Put the full grid and judge validation in the README appendix.

### Gaps
- DEC-0/DEC-2 don't state the user-simulation method (scripted vs LLM-simulated multi-turn). Its noise contribution can't be estimated until the runner exists.
- The per-run cost and latency of the deployed AgentCore stack are unknown here, so the runtime of the ~2,000–6,000 trial budget can't be estimated from these sources.
