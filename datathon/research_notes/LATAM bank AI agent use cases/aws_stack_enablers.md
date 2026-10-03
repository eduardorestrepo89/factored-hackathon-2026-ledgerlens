# AWS stack enablers and limits for an AI-first LATAM banking customer-service agent (AgentCore, Bedrock, Nova Sonic, Connect) — as of 2026-09-29

Scope note: FAST template stack (Strands agent on AgentCore Runtime, Gateway + Lambda tools over MCP, Policy/Cedar on Gateway, Cognito V3 pre-token identity propagation, Memory, Code Interpreter, Observability, Evaluations). Regions of interest: us-east-1, us-east-2, sa-east-1. Prices in USD. Where a source is third-party or conflicts with AWS docs, it is flagged.

## 1. AgentCore Policy / Cedar: what can policies condition on, can they enforce ownership, amount limits, confirmation, NL authoring, limits

### Takeaway
Policy is GA (Mar 2026) and enforced at the Gateway, outside agent code, default-deny with forbid-wins. Stateless Cedar can condition on JWT-claim principal tags, tool input parameters (`context.input.*`) and wall-clock time; amount caps and "customer_id in the token must equal customer_id in the tool call" are directly expressible. The August 2026 temporal policies (Dogwood language, Cedar-compatible) add session history: "only act on an account a prior lookup returned", cumulative-amount caps, one-time-use approvals and "approval before a write". Those are the pieces that make verified write actions such as blocking a card enforceable. Guardrails can also run inside policies against tool inputs and outputs.

### Cited Findings
- **Status/regions.** Policy was in preview at re:Invent (Dec 2025), and "Policy in AgentCore is available in all AWS Regions" at that preview — [AWS What's New Dec 2025](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-bedrock-agentcore-policy-evaluations-preview/). It went GA in Mar 2026: "available in thirteen AWS Regions", with policies "written in natural language that converts to Cedar" and stored in a policy engine attached to a Gateway — [AWS What's New Mar 2026](https://aws.amazon.com/about-aws/whats-new/2026/03/policy-amazon-bedrock-agentcore-generally-available/).
- **Principal types.** `AgentCore::OAuthUser` is created from the JWT `sub` claim and "OAuth principals support tags that contain JWT claims such as username, scope, role". `AgentCore::IamEntity` is used for IAM-authorized gateways; it has an `id` holding the IAM ARN and does not support tags — [Policy core concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-core-concepts.html); [Schema constraints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-schema-constraints.html).
- **Conditions.** `when` and `unless` clauses can condition on principal tags from the OAuth token and on context, e.g. `principal.department == "Engineering" && context.input.priority == "high"` — [AWS CDK aws_bedrockagentcore README](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html). The AWS Security blog shows the tag form `principal.hasTag("customer_tier") && principal.getTag("customer_tier") == "Gold"` combined with `unless { context.input.refundAmount > 1000 }` — [AWS Security Blog: Why Policy chose Cedar](https://aws.amazon.com/blogs/security/why-policy-in-amazon-bedrock-agentcore-chose-cedar-for-securing-agentic-workflows/).
- **Amount caps.** Documented examples include `context.input.coverage_amount <= 1000000` — [CDK Python README](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrock_agentcore_alpha/README.html) — and a refund cap plus business-hours window: `context.system.now.toTime() >= duration("9h") ... when { context.input.amount <= 2500 }` — [AWS ML Blog: Authoring Dogwood policies from natural language](https://aws.amazon.com/blogs/machine-learning/authoring-dogwood-policies-from-natural-language-in-amazon-bedrock-agentcore/).
- **Schema.** The Cedar schema is generated automatically from the Gateway's MCP tool manifest, and each tool becomes `AgentCore::Action::"Target___tool"`. "Only available context is `context.input`". `context.output` "can only be used with guardrails". Policies cannot use custom attributes on OAuthUser ("use tags instead") and cannot define new entity types. JSON types map to Cedar types: string→String, integer→Long, number→Decimal (truncated), object→Record, array→Set (order lost) — [Schema constraints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-schema-constraints.html).
- **Hard limits (none adjustable)** — [Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html); [Policy limitations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-limitations-section.html):
  - 1,000 policy engines per account per Region.
  - 1,000 policies per engine.
  - 10 KB per policy; 200 KB total per resource.
  - Cedar schema up to 400 KB across all tools of all gateways on an engine.
  - 50,000 generated (NL) policies per 7-day window per engine.
  - Decimals limited to 4 decimal places.
  - "Mixing `context.input.` and `context.output.` in a single invocation is rejected."
  - For NL2Cedar, custom claims must be supplied in the prompt.
- **NL authoring (NL2Cedar).** Requires a deployed Gateway and policy engine and "uses the AgentCore Gateway schema to generate valid Cedar policies" — [Writing policies in natural language](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-natural-language.html). Before deployment, automated-reasoning "semantic validation" flags overly permissive, overly restrictive and ineffective policies — [AWS Startups: Prove It Part 2](https://aws.amazon.com/aws-startups/learn/prove-it-part-2-formal-logic-cedar-policies-and-the-economics-of-verification/). Cedar Analysis also detects contradictory conditions, always-allow policies and conflicts across the policy set — [AWS Security Blog](https://aws.amazon.com/blogs/security/why-policy-in-amazon-bedrock-agentcore-chose-cedar-for-securing-agentic-workflows/). Temporal policies can also be written in natural language — [Authoring temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal-authoring.html).
- **Temporal policies (Dogwood).** Announced Aug 2026 (the What's New entry does not say "preview"). They can "enforce workflow sequencing, ensure tool arguments match prior call outputs, require human approval for privileged actions, and enforce data freshness". Gateway rate limiting per user or group arrived in the same launch — [AWS What's New Aug 2026](https://aws.amazon.com/about-aws/whats-new/2026/08/temporal-policies-agentcore/).
  - Operators: `formerly within`, `since within`, `count`, `sum`.
  - Requires the `x-amzn-bedrock-agentcore-policy-session-id` header, which the caller generates.
  - Adding or updating a temporal policy invalidates active sessions (HTTP 409).
  - Quotas: 20 temporal policies per engine, 3 temporal operators per policy, maximum window 24 h.
  - Supported in us-east-1, us-east-2 and sa-east-1 (plus others).
  - Gateway and all targets must be in the same account and Region.
  - The Gateway role needs `bedrock-agentcore:GetWorkloadAccessToken`.
  - Can run in `LOG_ONLY` before `ENFORCE`.
  - Source: [Temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html).
- **Documented temporal patterns.** All from [Authoring temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal-authoring.html):
  - **Output-to-input integrity:** `transfer_funds` is permitted only if an earlier `get_account_balance` response in the session had `output.accountId == context.input.toAccount`. This prevents fabricated accounts.
  - **One-time-use approval:** each approval is consumed by one action.
  - **Cumulative budget:** forbid when the `sum` of `input.amount` in the window reaches a threshold.
  - **Session rate limiting.**
  - **Cool-down.**
  - **Block after a prior denial:** match an `::error` event.
  - **Combined temporal + guardrail + Cedar conditions** in one policy.
  - Caveat from the same page: "This limit applies only within a single session... the caller supplies the session ID, they can reset the count by starting a new session." Cumulative sums "do not aggregate across sessions".
- **Approval example.** The doc example permits `SellShares` only if an `ApproveSale` response matched the same stock and shares with `output.approved: true` within 1 h — [Temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html). The FAQ says temporal rules can require "that a recorded human approval exist before a consequential action and be consumed by a single action rather than reused", and "that permissions narrow automatically when a human operator is no longer engaged" — [AgentCore FAQs](https://aws.amazon.com/bedrock/agentcore/faqs/).
- **Guardrails in policies.** Guardrails "evaluates outputs from authorized agent actions and inputs to gateway targets for prompt injection attempts, harmful content, and sensitive data exposure" at the gateway layer — [AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html). Syntax example: `suppressOutput (...) when guardrails { BedrockGuardrails::ContentFilter(["HATE"],[context.output.message])["HATE"].confidenceScore.greaterThan(decimal("0.2")) }` — [Guardrails in policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html). "Detection is probabilistic, but policy enforcement stays deterministic" — [AgentCore FAQs](https://aws.amazon.com/bedrock/agentcore/faqs/).
- **Pricing.** Authorization requests cost $0.000025 each. NL policy authoring costs $0.13 per 1,000 tokens. "First 100 temporal policies per engine incur no additional authorization charges" — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).
- **Interceptors.** Gateway Lambda interceptors can inject context that Cedar then enforces, e.g. data-residency rules "based on context attributes injected by an interceptor" — [AWS ML Blog: Policy and Lambda interceptors](https://aws.amazon.com/blogs/machine-learning/secure-ai-agents-with-policy-and-lambda-interceptors-in-amazon-bedrock-agentcore-gateway/). A banking pattern shows read tools permitted for all authenticated users, writes restricted, and destructive tools forbidden — [AWS ML Blog: multi-account agent with Gateway and MCP](https://aws.amazon.com/blogs/machine-learning/build-a-multi-account-ai-agent-with-agentcore-gateway-and-mcp/).

### Inferences
- **"Only this customer's product_id"** is feasible in two ways:
  - Stateless: have the Cognito V3 pre-token Lambda add a `customer_id` claim and write `principal.getTag("customer_id") == context.input.customer_id` (tags = JWT claims).
  - Temporal: output-to-input integrity, e.g. permit `block_card(card_id)` only if a prior `get_card(...)` response in the session returned `output.card_id == context.input.card_id`.
  - Keep ownership checks in the tool Lambda too (defense in depth), because temporal controls are session-scoped and the session ID is caller-supplied.
- **Amount limits.** Per-call caps use stateless Cedar. Per-session cumulative caps use temporal `sum` with a window of 24 h or less. Cross-session and daily per-customer limits must live in the core-banking tool or DB (e.g. Aurora), not in Policy.
- **Confirmation requirement.** The strongest in-stack pattern:
  1. A `confirm_action` tool whose `approved=true` output is produced only by a user action outside the LLM's control (UI button or MCP elicitation form, see Q2).
  2. A temporal permit on the write tool that requires a matching `confirm_action::response` with the same parameters, plus the one-time-use `since` pattern.
  - A stateless `context.input.confirmed == true` is weak, because the LLM sets that parameter itself.
- **Demo-friendly novelty.** "Policy denied" traces and LOG_ONLY vs ENFORCE show deterministic safety, and NL→Cedar authoring by a compliance officer is visually compelling. Both are feasible in about 6 days since the repo already has Policy + Gateway.

### Gaps
- Whether a JWT claim that is an array (e.g. a list of the customer's card IDs) becomes a Cedar Set tag, so that `context.input.card_id in principal.getTag(...)` works, is not documented in the pages read.
- Whether temporal `output.<field>` can match an element inside an array output (e.g. a list of cards) is not documented; the examples use scalar outputs.
- The full list of the 13 GA regions for Policy was not retrieved; sa-east-1 support is inferred from the temporal-policies region table, which lists São Paulo.
- The temporal policies What's New does not state GA vs preview explicitly.

## 2. AgentCore Evaluations, Identity (inbound/outbound, step-up), Memory strategies, Observability

### Takeaway
Evaluations is GA (Mar 2026). It offers 13 core built-in LLM-judge evaluators at session, trace and tool-call level; per the AWS ML Blog the catalog has grown to include trajectory, skill and ContextRelevance evaluators. It also supports custom LLM-judge and Lambda code-based evaluators, DeepEval/AutoEval third-party evaluators, and three modes (on-demand, online with sampling, batch at 25% off), with ground truth (expected response, assertions, expected trajectory) available on-demand. Identity provides inbound JWT validation with custom-claim rules and outbound OAuth (2LO, 3LO, OBO token exchange); it has no native "step-up auth" feature, but Gateway MCP elicitation (form/URL) and Strands interrupt hooks provide human-in-the-loop confirmation. Memory offers semantic, summarization, user-preference and episodic strategies with asynchronous extraction.

### Cited Findings
- **Evaluations GA.** GA in Mar 2026 with "Two evaluation types... online evaluation... and on-demand evaluation". It ships 13 built-in evaluators, Ground Truth ("reference answers, behavioral assertions, and expected tool execution sequences"), and custom evaluators "using LLM-based evaluation or Python/JavaScript Lambda functions". "Available in nine AWS Regions" — [AWS What's New Mar 2026](https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available/). The preview (Dec 2025) ran in us-east-1, us-west-2, ap-southeast-2 and eu-central-1 — [AWS What's New Dec 2025](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-bedrock-agentcore-policy-evaluations-preview/).
- **The 13 built-ins:** Correctness, Faithfulness, Helpfulness, Response Relevance, Conciseness, Coherence, Instruction Following, Refusal, Goal Success Rate, Tool Selection Accuracy, Tool Parameter Accuracy, Harmfulness, Stereotyping — [AgentCore FAQs](https://aws.amazon.com/bedrock/agentcore/faqs/). Levels:
  - SESSION: GoalSuccessRate.
  - TRACE: Helpfulness, Correctness and the rest.
  - TOOL_CALL: ToolSelectionAccuracy, ToolParameterAccuracy.
  - Source: [CDK README](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html).
- **Expanded catalog** (per an AWS ML Blog): TrajectoryExactOrderMatch, TrajectoryInOrderMatch and TrajectoryAnyOrderMatch (these need `expectedTrajectory`), SkillSelectionAccuracy, SkillInstructionFollowing and ContextRelevance. It also lists third-party evaluators "from the DeepEval and AutoEval open-source libraries". Its advice: "Start with four to five evaluators for CI... add safety evaluators (Harmfulness, Stereotyping, Refusal) for customer-facing agents" — [AWS ML Blog: AgentCore + GitHub Actions](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/).
- **Three modes** — [AWS ML Blog: AgentCore + GitHub Actions](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/):
  - On-demand: "you provide span data directly in the API call".
  - Online: "continuously monitors production traffic with configurable sampling rates".
  - Batch: "scores multiple sessions in a single asynchronous job".
- **On-demand vs online details:**
  - On-demand results come back in the API response, "limited to 10 evaluations per call" — [AWS ML Blog: Build reliable AI agents with AgentCore Evaluations](https://aws.amazon.com/blogs/machine-learning/build-reliable-ai-agents-with-amazon-bedrock-agentcore-evaluations/).
  - Online evaluation "can only use evaluators that do not require ground truth"; custom judges referencing `{expected_response}` or `{assertions}` "are on-demand only".
  - Online results land in `/aws/bedrock-agentcore/evaluations/results/{config_id}` in CloudWatch, which you can alarm on.
  - Online config example: `samplingPercentage: 25.0`.
  - Source for the last three: [AWS ML Blog: Evaluate any agent framework](https://aws.amazon.com/blogs/machine-learning/evaluate-any-agent-framework-with-amazon-bedrock-agentcore-evaluations/).
- **Custom evaluator config.** Custom evaluators use either LLM-as-judge (instructions, a model ID such as `us.anthropic.claude-sonnet-4-6`, and a categorical or numeric rating scale) or code-based Lambda — [CDK Evaluator class](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/Evaluator.html).
- **Optimization features (Jun 2026).** Batch evaluations, recommendations and A/B testing are GA in 14 Regions; failure, intent and trajectory "insights" are in preview in 13 Regions — [AWS What's New Jun 2026](https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-agentcore-new-optimization-capabilities/).
- **Evaluations pricing.** Built-in evaluators cost $0.0024 per 1K input tokens and $0.012 per 1K output tokens. Custom evaluators cost $1.50 per 1,000 evaluations. Batch gets a 25% discount — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).
- **Observability** is OTEL-compatible and delivered through CloudWatch dashboards — [AWS What's New AgentCore GA Oct 2025](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/). Evaluations appear in the CloudWatch GenAI observability console alongside Application Signals, Alarms and Logs Insights — [AWS What's New Dec 2025 (CloudWatch)](https://aws.amazon.com/about-aws/whats-new/2025/12/cloudwatch-genai-observability-agentcore-evaluations/). Policy metrics go to the `AWS/Bedrock-AgentCore` namespace, and Gateway spans go to `aws/spans` once traces are enabled — [Temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html). Observability is billed at standard CloudWatch rates — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).
- **Identity, inbound.** The JWT authorizer (the same config for Runtime and Gateway) takes a discovery URL, allowed audiences, allowed clients, allowed scopes and required custom claims (STRING/STRING_ARRAY) — [Configure inbound JWT authorizer](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html). Example: the claim `department` must match `["Sales","Finance"]` with `CONTAINS_ANY` — [AWS Security Blog: Propagate user authorization context](https://aws.amazon.com/blogs/security/propagate-user-authorization-context-in-ai-agents-with-amazon-bedrock-agentcore/).
- **Identity, outbound.** Three OAuth patterns: 2LO/M2M, 3LO (user consent via browser redirect) and OBO token exchange (RFC 8693) — [AWS Security Blog](https://aws.amazon.com/blogs/security/propagate-user-authorization-context-in-ai-agents-with-amazon-bedrock-agentcore/). OBO "binding both the user's identity and the agent's identity into the resulting token", RFC 8693 or RFC 7523 — [Supported authentication patterns](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/common-use-cases.html). A token vault stores user OAuth tokens and API keys — [AgentCore FAQs](https://aws.amazon.com/bedrock/agentcore/faqs/). Identity is "available at no additional charge" when used through Runtime or Gateway — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).
- **Step-up and confirmation patterns:**
  - **Gateway elicitation pass-through.** Form mode, e.g. "Confirm you want to proceed with this refund?"; URL mode, e.g. an OAuth consent page or external approval — [AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html); [Use elicitation with your gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-mcp-elicitation.html). Elicitation "requires both streaming and sessions to be enabled", its timeout "is governed by the AgentCore Gateway connection timeout", and it works only if the client declares elicitation support — [AWS ML Blog: Extending MCP support for Gateway](https://aws.amazon.com/blogs/machine-learning/extending-mcp-support-for-amazon-bedrock-agentcore-gateway-2/).
  - **Strands `BeforeToolCallEvent` hook.** It can `interrupt` the loop for human approval (y/n/trust) before sensitive tools run, deployed on AgentCore Runtime — [AWS ML Blog: HITL constructs](https://aws.amazon.com/blogs/machine-learning/human-in-the-loop-constructs-for-agentic-workflows-in-healthcare-and-life-sciences/).
  - **Auth0 CIBA push approval.** An out-of-band approval channel for high-risk actions (partner option) — [AWS APN Blog: Auth0 + AgentCore](https://aws.amazon.com/blogs/apn/securing-enterprise-ready-ai-agents-with-auth0-for-ai-agents-and-amazon-bedrock-agentcore/).
- **Memory:**
  - Built-in strategies: Summarization, Semantic, User Preferences; custom strategies can use specific models and prompts — [CDK README](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/README.html).
  - Episodic memory, launched Dec 2025 — [AWS What's New Dec 2025](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-bedrock-agentcore-policy-evaluations-preview/). It stores procedural knowledge "as reflections tied to episodic memory" — [AWS ML Blog: lifecycle policies for AgentCore memory](https://aws.amazon.com/blogs/machine-learning/designing-lifecycle-policies-for-agentcore-memory/).
  - Long-term extraction "is asynchronous"; use namespaces such as `customer-support/user/<id>` — [AWS ML Blog: LTM deep dive](https://aws.amazon.com/blogs/machine-learning/building-smarter-ai-agents-agentcore-long-term-memory-deep-dive/).
  - Pricing: short-term $0.25 per 1K new events; LTM storage $0.75 per 1K records per month (built-in strategies) or $0.25 (self-managed); retrieval $0.50 per 1K — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).
- **Regional availability.** The AgentCore product is available in us-east-1, us-east-2 and sa-east-1 — AWS Regional Services List, queried via the AWS Knowledge regional-availability API ([Regional product services](https://aws.amazon.com/about-aws/global-infrastructure/regional-product-services/)).

### Inferences
- **Credible pass-rate reporting** from AgentCore:
  - Run on-demand or batch evaluation over a fixed scenario set (ES and PT-BR) with ground-truth assertions and expected trajectories, for example "block_card called exactly once, after confirm".
  - Threshold each evaluator's score into pass/fail and report per-evaluator pass rates with n.
  - Add a custom Lambda evaluator for deterministic checks (wrong-customer data, write without confirmation, PII in the response).
  - Use online evaluation at a sampled rate for production-style monitoring.
- **LTM caution.** Memory LTM should not hold data the agent could later act on without re-verification; memory poisoning is OWASP ASI06 (see Q6).
- **Step-up without a new IdP.** Gateway elicitation URL mode pointing at a Cognito re-auth or OTP page is the in-stack "step-up" route. Verify that the FAST frontend's MCP client path supports elicitation: in FAST the agent, not the browser, is the MCP client, so the elicitation must be relayed to the UI.

### Gaps
- The nine Evaluations GA regions were not enumerated in the sources retrieved, so us-east-2 and sa-east-1 support is unconfirmed.
- Whether built-in evaluator judge prompts are validated for Spanish and Portuguese transcripts: no source found.
- No AgentCore Identity feature named "step-up authentication" was found; only the patterns above.
- CloudWatch prerequisites (e.g. Transaction Search enablement) were not verified in this pass.

## 3. Voice: Nova 2 Sonic (languages, tool use, latency, pricing, AgentCore Runtime fit) and Amazon Connect options

### Takeaway
Nova 2 Sonic (GA Dec 2025) supports Spanish (es-US voices) and Brazilian Portuguese (pt-BR voices), with automatic language switching, function calling, asynchronous tool calls and barge-in. It runs through `InvokeModelWithBidirectionalStream` and can be hosted on AgentCore Runtime over WebSocket bidirectional streaming (Strands BidiAgent is experimental). Hard limits:
- In-Region only, in us-east-1, us-west-2, eu-north-1 and ap-northeast-1 (not us-east-2 or sa-east-1).
- 20 concurrent streams per account per Region, not adjustable.
- 8-minute connection limit.
- The Bedrock model card lists Guardrails as not supported.

Amazon Connect's Nova Sonic self-service is GA for English and Spanish in us-east-1 and us-west-2, and gives native escalation to humans plus generative post-contact summaries.

### Cited Findings
- **Capabilities.** Nova 2 Sonic has a bidirectional streaming API and multilingual support "with automatic language detection and switching" (English variants, French, Italian, German, Spanish, Portuguese, Hindi). It offers polyglot voices, "Intelligent turn-taking", graceful interruptions, "Function calling and agentic workflow support", and "Asynchronous tool handling... allowing the assistant to continue speaking while tools process". Cross-modal audio+text input is supported. "Connection limit of 8 minutes, with connection renewal and session continuation pattern available in code samples" — [Nova 2 user guide: Speech-to-Speech](https://docs.aws.amazon.com/nova/latest/nova2-userguide/using-conversational-speech.html).
- **Voices.** Spanish is locale es-US (lupe, carlos). Portuguese is locale pt-BR (carolina, leo) — [Nova 2 Sonic language support](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-language-support.html). The responsible-AI service card confirms "Portuguese (Brazilian)" and tool use "to... complete transactions" — [Nova 2 Sonic service card](https://docs.aws.amazon.com/ai/responsible-ai/nova-2-sonic/overview.html).
- **GA and benchmarks.** GA announced Dec 2025, claiming BFCL (function calling) and ComplexFuncBench improvements — [AWS News Blog](https://aws.amazon.com/blogs/aws/introducing-amazon-nova-2-sonic-next-generation-speech-to-speech-model-for-conversational-ai/).
- **Bedrock model card:**
  - Model ID `amazon.nova-2-sonic-v1:0`; Geo and Global inference IDs "Not supported".
  - Regions listed: us-east-1, us-west-2, eu-north-1, ap-northeast-1.
  - "The default quota for Nova 2 Sonic is 20 concurrent `InvokeModelWithBidirectionalStream` sessions per AWS account in each supported Region. This quota is not adjustable."
  - Features Not Supported on bedrock-runtime include "Guardrails... Knowledge base... Agents".
  - EOL no sooner than Dec 2, 2026.
  - Source: [Bedrock model card: Nova 2 Sonic](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-sonic.html).
  - **Conflict:** an AWS ML blog says Nova 2 Sonic "can be integrated with key Amazon Bedrock features, including Guardrails, Agents, multimodal RAG, and Knowledge Bases" — [AWS ML Blog: conversational podcasts](https://aws.amazon.com/blogs/machine-learning/building-real-time-conversational-podcasts-with-amazon-nova-2-sonic/). This contradicts the model card.
- **AgentCore Runtime fit.** Runtime supports "WebSocket streaming for real-time bidirectional communication" — [Runtime WebSocket guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html). The AWS sample deploys either a native Nova Sonic WebSocket server or `strands.experimental.bidi` `BidiAgent` with `BidiNovaSonicModel` (the sample uses `amazon.nova-sonic-v1:0`) at `@app.websocket("/ws")`, with tools passed to the agent constructor — [AWS ML Blog: bidirectional streaming in Runtime](https://aws.amazon.com/blogs/machine-learning/bi-directional-streaming-for-real-time-agent-interactions-now-available-in-amazon-bedrock-agentcore-runtime/). Browser clients get a SigV4 pre-signed WebSocket URL from an intermediary server; Pipecat is an alternative framework — [AWS ML Blog: Pipecat on AgentCore](https://aws.amazon.com/blogs/machine-learning/deploy-voice-agents-with-pipecat-and-amazon-bedrock-agentcore-runtime-part-1/).
- **Pricing (third-party, not verified on the AWS page).** Nova 2 Sonic speech is reportedly $3 per 1M input speech tokens and $12 per 1M output speech tokens; text is $0.33 in and $2.75 out per 1M — reported by third-party trackers surfaced in search, e.g. [llm-stats Nova 2 Sonic](https://llm-stats.com/models/nova-2-sonic) and [getmaxim cost calculator](https://www.getmaxim.ai/bifrost/llm-cost-calculator/provider/bedrock/model/amazon.nova-2-sonic-v1-0). The AWS [Nova pricing](https://aws.amazon.com/nova/pricing/) and [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) pages did not render these figures in the fetch.
- **Amazon Connect agentic self-service** with Nova Sonic: "available in US East (N. Virginia) and US West (Oregon)... fully available in English and Spanish, and in preview for French, Italian, and German", "maintaining the ability to escalate to a live representative at any point" — [AWS What's New Nov 2025](https://aws.amazon.com/about-aws/whats-new/2025/11/amazon-connect-agentic-self-service/); [Connect release notes](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-release-notes.html). Nova Sonic is configured as the S2S model for a Conversational AI bot locale, while "Amazon Connect continues to manage orchestration, intents, and flows" — [Configure Nova Sonic S2S](https://docs.aws.amazon.com/connect/latest/adminguide/nova-sonic-speech-to-speech.html).
- **Connect language expansion.** Mar 2026: 13 new languages including Spanish (Mexico), 40 locales in total — [AWS What's New Mar 2026](https://aws.amazon.com/about-aws/whats-new/2026/03/amazon-connect-voice-ai-agents-13-languages/). Jul 2026: "over 50 languages including Spanish... Portuguese" and over 100 new voices — [AWS What's New Jul 2026](https://aws.amazon.com/about-aws/whats-new/2026/07/amazon-connect-agentic-voice/). Connect also supports third-party Deepgram (STT) and ElevenLabs (TTS) — [AWS Contact Center Blog](https://aws.amazon.com/blogs/contact-center/leading-the-conversation-with-conversational-ai-in-amazon-connect/).
- **Handoff artifacts.** Generative AI post-contact summaries are GA, available to agents on the CCP (voice and email), to supervisors (voice, chat, email), and via API and Kinesis Data Streams — [View generative AI post-contact summaries](https://docs.aws.amazon.com/connect/latest/adminguide/view-generative-ai-contact-summaries.html); [Connect generative AI blog](https://aws.amazon.com/blogs/contact-center/increasing-agent-productivity-with-generative-ai-in-amazon-connect/).

### Inferences
- **Voice demo in 6 days.** Feasible only if the voice agent's Runtime is deployed in us-east-1 (Nova 2 Sonic has no us-east-2 or sa-east-1 endpoint and no cross-region profile). Use the Strands BidiAgent sample with the same Gateway MCP tools so Policy still guards writes.
  - Treat the 20-stream cap and the 8-minute reconnection pattern as demo constraints.
  - Because the model card says Guardrails is not supported natively, rely on Gateway-level Policy and Guardrails-in-policy for safety on voice.
- **Human handoff without Connect.** Within the current stack: the agent writes a structured case (transcript + LLM summary + verified identity + attempted actions) to Aurora or DynamoDB and publishes to SNS. Connect is the "real" production path, but setup adds scope and Connect's Nova Sonic S2S is limited to us-east-1 and us-west-2.
- **Spanish variant.** es-US voices may sound non-local to Mexican, Colombian or Argentine customers; Spanish (Mexico) exists in Connect's broader voice catalog.

### Gaps
- No primary AWS latency figure (time-to-first-audio) for Nova 2 Sonic was found.
- No speech-tokens-per-minute conversion was found, so per-minute voice cost could not be computed from primary sources.
- Whether Connect's Nova Sonic S2S (as opposed to Connect's other voice stack) now supports pt-BR as of Sep 2026 is unconfirmed; the Jul 2026 note does not say which engine.
- Connect availability in sa-east-1, and a documented "bring your own AgentCore agent into Connect" integration, were not researched or found.

## 4. Bedrock Guardrails: Spanish/Portuguese support, prompt attacks, PII, contextual grounding, Automated Reasoning

### Takeaway
Use the Standard tier: content filters, prompt-attack detection and denied topics are "Optimized and supported" for both Spanish and Portuguese. PII filters also support both. Contextual grounding checks support only English, French and Spanish, not Portuguese. Word filters support only English, French and Spanish. Automated Reasoning checks are GA in six Regions (incl. us-east-1 and us-east-2) but English (US) only, so they cannot directly verify Spanish or Portuguese answers. Critically, the prompt-attack filter does not evaluate tool results.

### Cited Findings
- **Language table** — [Guardrails supported languages](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-supported-languages.html):

  | Policy | Tier | Spanish | Portuguese | Notes |
  | --- | --- | --- | --- | --- |
  | Content filters and prompt attacks | Standard | Optimized and supported | Optimized and supported | |
  | Content filters and prompt attacks | Classic | Supported | Not supported | Classic covers English, French, Spanish only |
  | Denied topics | Standard | Optimized | Optimized | Classic covers English, French, Spanish only |
  | Word filters | — | Supported | Not supported | English, French, Spanish only |
  | Sensitive information (PII) | — | Optimized | Optimized | |
  | Contextual grounding | — | Optimized | Not supported | English, French, Spanish only |

  The page also warns: "Guardrails are ineffective with languages that aren't supported."
- **Prompt attacks and tool results.** Prompt attack detection covers jailbreaks, prompt injection and prompt leakage (Standard tier only). The `InvokeGuardrailChecks` API offers resource-less checks "For agentic applications" — [Amazon Bedrock FAQs](https://aws.amazon.com/bedrock/faqs/). With InvokeModel, input tags are required: "If there are no tags, prompt attacks... will not be filtered". Also: "The prompt attack filter does not evaluate tool results. Content in `messages[].content[].toolResult` is not assessed for prompt attacks" — [Detect prompt attacks](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html).
- **AWS guidance on indirect injection.** Tag external or RAG or tool-derived content as user input, use unique tag suffixes per request, and call `ApplyGuardrail` inside tool Lambdas because "Current Amazon Bedrock Agents implementation doesn't pass tool input and output through guardrails" — [AWS ML Blog: indirect prompt injections](https://aws.amazon.com/blogs/machine-learning/securing-amazon-bedrock-agents-a-guide-to-safeguarding-against-indirect-prompt-injections/). The newer route is Guardrails inside AgentCore Policy, evaluating tool inputs and outputs at the Gateway (see Q1) — [AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html).
- **PII filters** can block or mask, can use custom regex, and offer 31 pre-configured PII types — [AWS ML Blog: Guardrails code domain](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-guardrails-expands-support-for-code-domain/).
- **Automated Reasoning (AR) checks** "detect factual inaccuracies... suggest corrections, and explain why responses are accurate" against an AR policy — [Amazon Bedrock FAQs](https://aws.amazon.com/bedrock/faqs/).
  - GA regions: us-east-1, us-west-2, us-east-2, eu-central-1, eu-west-3, eu-west-1. "Automated Reasoning checks currently support English (US) only" — [What are Automated Reasoning checks](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html).
  - Policies are built from an uploaded PDF (rules + variables); the confidence threshold ranges 0.00–1.00; up to two AR policies per guardrail — [AWS ML Blog: AR Part 1](https://aws.amazon.com/blogs/machine-learning/build-reliable-ai-systems-with-automated-reasoning-on-amazon-bedrock-part-1/). There is a financial-services walkthrough — [AWS ML Blog: AR for financial services](https://aws.amazon.com/blogs/machine-learning/build-verifiable-explainability-into-financial-services-workflows-with-automated-reasoning-checks-for-amazon-bedrock-guardrails/).
  - Older blogs describing a US West (Oregon) preview are superseded by the GA doc — [AWS ML Blog (preview era)](https://aws.amazon.com/blogs/machine-learning/build-responsible-ai-applications-with-amazon-bedrock-guardrails/).
- **Guardrails pricing** per 1,000 text units — [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/):
  - Content filters: $0.15.
  - Denied topics: $0.15.
  - Sensitive information: $0.10.
  - Contextual grounding: $0.10.
  - Automated Reasoning: $0.17 per policy.

### Inferences
- **Merchant-name injection.** Model-level Guardrails will not catch a prompt injection inside a transaction's merchant field returned by a tool, because tool results are not scanned. Scan tool outputs with Guardrails-in-Policy at the Gateway (`context.output`) or with `ApplyGuardrail` in the Lambda.
- **Grounding for PT-BR.** Contextual grounding cannot be used for Portuguese answers. Options: an LLM-judge Faithfulness evaluator, or translating to Spanish or English before the check. Latency and cost trade-offs are untested.
- **"Formally verified policy answers"** (e.g. fee or eligibility rules) with AR checks is feasible only on an English pivot. One option is to have the agent produce an English canonical claim ("customer tier X, fee Y") that is AR-checked, then render it in ES or PT. This is novel but adds pipeline risk in 6 days.

### Gaps
- Whether PII entity types cover LATAM identifiers (Brazil CPF/CNPJ, Mexico CURP/RFC, Colombia cédula) natively: not verified; they likely need custom regex.
- The definition of a "text unit" (character count) was not retrieved in this pass.
- Whether Guardrails-in-Policy at the Gateway has the same language coverage as standalone Guardrails is not stated.

## 5. Model choice and cost for a Spanish/Portuguese tool-using agent (with worked estimate)

### Takeaway
On Bedrock, the practical choices are:

| Model | Input $/1M | Output $/1M | Cache read $/1M | Notes |
| --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 | $2 | $10 | $0.20 | Launched on Bedrock Sep 28, 2026, global inference profile only |
| Claude Sonnet 4.6 | $3 | $15 | — | More mature |
| Claude Haiku 4.5 | $1 | $5 | — | Cheapest Claude option |
| Claude Opus 5.5 | $4 | $20 | $0.20 | |
| Amazon Nova 2 Lite | ~$0.30 | ~$2.50 | — | Third-party-reported price |

A 10-turn, 5-tool-call conversation costs roughly $0.09 on Sonnet 5.5 with prompt caching (about $0.24 without). AgentCore platform fees add about 1–2 cents unless online evaluation samples heavily.

### Cited Findings
- **Anthropic list prices** (the first-party API; Bedrock bills separately):
  - Sonnet 5.5: $2 in / $2.50 5-minute cache write / $4 1-hour write / $0.20 cache hit / $10 out.
  - Sonnet 4.6: $3 / $3.75 / $6 / $0.30 / $15.
  - Haiku 4.5: $1 / $1.25 / $2 / $0.10 / $5.
  - Opus 5.5: $4 / $5 / $8 / $0.20 / $20.
  - Cache write is 1.25x (5 min) or 2x (1 h); cache read is 0.1x (0.05x on Opus 5.5).
  - "Claude 4.7 and later models... use a newer tokenizer... approximately 30% more tokens for the same text."
  - Tool-use system prompt: 286 tokens (Sonnet 5.5, auto).
  - On Bedrock, "Regional and multi-region endpoints include a 10% premium over global endpoints" for Claude 4.5 and later.
  - Source: [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing).
- **Claude Sonnet 5.5 on Bedrock** — [Bedrock model card: Claude Sonnet 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html):
  - Launch Sep 28, 2026; 1M context; 128K output.
  - Adaptive thinking on by default, effort low–max with default high.
  - bedrock-runtime access only via `global.anthropic.claude-sonnet-5-5` (in-Region URL "N/A"; the Data residency section lists only Global).
  - On bedrock-runtime, supports Guardrails, implicit and explicit prompt caching (minimum 512 tokens per checkpoint, 4 checkpoints, 5-minute or 1-hour TTL), Agents and Knowledge bases.
  - Does not support "Count tokens" or "Structured outputs" on bedrock-runtime.
  - Billed via AWS Marketplace under the model provider.
- **Bedrock page figures** (as rendered in the fetch) — [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/):
  - Mistral Large 3: $0.50 / $1.50.
  - DeepSeek v3.2: $0.62 / $1.85.
  - Qwen3 32B: $0.15 / $1.20.
  - The fetch did not render current Claude or Nova rows.
- **Nova 2 Lite** at $0.30 in / $2.50 out per 1M is reported by third-party trackers, e.g. [pricepertoken](https://pricepertoken.com/pricing-page/model/amazon-nova-2-lite-v1) and [OpenRouter](https://openrouter.ai/amazon/nova-2-lite-v1). Not verified on an AWS page.
- **AgentCore unit prices** — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/):
  - Runtime (v1): $0.0895 per vCPU-hour and $0.00945 per GB-hour, with "I/O wait and idle time is free" (v2: $0.1276 per vCPU-hour, $0.0169 per GB-hour).
  - Gateway: $0.005 per 1K invocations.
  - Policy: $0.000025 per authorization.
  - Memory: $0.25 per 1K events; $0.50 per 1K retrievals.
  - Code Interpreter: $0.0895 per vCPU-hour.
  - Evaluations: built-in $0.0024 per 1K input and $0.012 per 1K output tokens; custom $1.50 per 1K evaluations.

### Inferences
**Worked estimate per conversation.** Assumptions (mine, not sourced):
- 10 user turns and 5 tool calls, so 15 model invocations.
- Static prefix of about 4,000 tokens (Spanish system prompt, ~10 tool schemas, 286-token tool prompt).
- Each turn adds about 200 tokens (user ~50, reply ~150). Each tool call adds about 480 tokens (call ~80, result ~400).
- Ending history about 4,400 tokens.
- Total input across calls about 93K tokens.
- Output about 5K tokens including light adaptive thinking.

| Model | No caching | With 5-minute caching |
| --- | --- | --- |
| Sonnet 5.5 | 93K×$2/M + 5K×$10/M ≈ $0.186 + $0.05 = **$0.24** | ~8.4K written×$2.50/M ($0.021) + ~84.6K read×$0.20/M ($0.017) + output $0.05 ≈ **$0.09** |
| Haiku 4.5 | ≈ **$0.12** | ≈ **$0.045** |
| Opus 5.5 | ≈ **$0.47** | ≈ **$0.16** |
| Nova 2 Lite (third-party price, no caching assumed) | ≈ **$0.04** | — |

- **Regional premium.** Add 10% if a regional or geo Claude endpoint is used. Sonnet 5.5 currently exposes only the global profile.
- **Tokenizer and language.** Add the tokenizer effect: 4.7+ models produce about 30% more tokens. Spanish and Portuguese probably tokenize less efficiently than English (unmeasured).
- **Platform overhead per conversation:**
  - Gateway and Policy for about 7 MCP calls: well under $0.001.
  - Memory: about 20 events, about $0.005, plus 1–2 retrievals, about $0.001.
  - Runtime: roughly $0.002–0.005 at 1 vCPU/2 GB with mostly idle I/O.
  - Guardrails: about 20 text units × ($0.15 + $0.10)/1K, about $0.005.
- **Evaluation spend.** A single built-in evaluator judging a ~6K-token trace costs about $0.018. At 100% online sampling with 3–4 evaluators, evaluation can exceed inference cost, so sample 10–25% online and use batch (25% off) for reports.
- **Recommendation for a 6-day build.** Sonnet 4.6 or Sonnet 5.5 as the main agent, with Haiku 4.5 or Nova 2 Lite for cheap sub-tasks (classification, summarization for handoff). Sonnet 5.5 is 1 day old on Bedrock and does not support structured outputs on bedrock-runtime, which is a risk for a demo.
- **Residency.** Global-only routing may matter for LATAM data-residency narratives (e.g. LGPD); cite as a limitation.

### Gaps
- Bedrock's own current Claude and Nova price rows could not be read from the AWS pricing page; the table assumes Bedrock global-endpoint prices equal Anthropic list prices.
- No multilingual (ES/PT) agent benchmark comparing these models was found.
- sa-east-1 in-Region availability for Haiku 4.5 or Sonnet 4.6 was not checked.
- Nova 2 Lite and Nova 2 Sonic prices come from third-party sites only.

## 6. Security best practice for tool-using agents (indirect injection, OWASP, plan-then-execute / dual-LLM / CaMeL, confirmation + read-back)

### Takeaway
Current consensus: model-level filters are probabilistic, so consequential actions need architectural constraints.
- Untrusted data, such as a merchant name, must not be able to trigger or re-parameterize write actions. Use plan-then-execute or action-selector patterns, dual-LLM or CaMeL-style data/control separation, least-privilege tools and deterministic policy at the tool boundary, plus human confirmation with read-back for writes.
- OWASP maps these risks: LLM01 Prompt Injection and LLM06 Excessive Agency (2025 LLM list); ASI01 Agent Goal Hijack, ASI02 Tool Misuse, ASI03 Identity & Privilege Abuse, ASI06 Memory & Context Poisoning and ASI09 Human-Agent Trust Exploitation (Agentic Top 10, Dec 2025).
- AgentCore's Gateway Policy (stateless + temporal + Guardrails) is the in-stack enforcement point.

### Cited Findings
- **OWASP Top 10 for LLM Applications 2025:** LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Supply Chain, LLM04 Data and Model Poisoning, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM08 Vector and Embedding Weaknesses, LLM09 Misinformation, LLM10 Unbounded Consumption — summarized by [Invicti](https://www.invicti.com/blog/web-security/owasp-top-10-risks-llm-security-2025) (secondary; the primary is OWASP GenAI).
- **OWASP Top 10 for Agentic Applications (2026 edition, released Dec 9, 2025):** ASI01 Agent Goal Hijack, ASI02 Tool Misuse and Exploitation, ASI03 Identity and Privilege Abuse, ASI04 Agentic Supply Chain, ASI05 Unexpected Code Execution, ASI06 Memory & Context Poisoning, ASI07 Insecure Inter-Agent Communication, ASI08 Cascading Failures, ASI09 Human-Agent Trust Exploitation, ASI10 Rogue Agents — [OWASP GenAI resource page](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/); list as summarized by [Teleport](https://goteleport.com/blog/owasp-top-10-agentic-applications/).
- **Design patterns paper** (Google, Microsoft, IBM, ETH Zurich, EPFL; arXiv 2506.08837). Six patterns: Action-Selector, Plan-Then-Execute, LLM Map-Reduce, Dual LLM, Code-Then-Execute, Context-Minimization. The principle: "once an LLM agent has ingested untrusted input, it must be constrained so that it is impossible for that input to trigger any consequential actions" — [arXiv 2506.08837](https://arxiv.org/abs/2506.08837); [Simon Willison summary](https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/).
- **CaMeL** (Google, Google DeepMind, ETH Zurich). A privileged LLM plans from the trusted user query; a quarantined LLM parses untrusted data without tool access; a custom interpreter tracks control and data flow with capabilities and enforces policies at tool-call time. It solves 77% of AgentDojo tasks "with provable security" vs 84% undefended — [arXiv 2503.18813](https://arxiv.org/abs/2503.18813).
- **Guardrails gap.** The Guardrails prompt-attack filter skips `toolResult` content — [Detect prompt attacks](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html). AWS recommends tagging external content and running `ApplyGuardrail` on tool I/O — [AWS ML Blog: indirect prompt injections](https://aws.amazon.com/blogs/machine-learning/securing-amazon-bedrock-agents-a-guide-to-safeguarding-against-indirect-prompt-injections/).
- **Temporal policies against injection.** They "prevent data fabrication between tool calls, cap cumulative financial exposure per session, and require human approval for high-value actions". Because they run at the Gateway, "the agent cannot intercept or manipulate them" — [AWS ML Blog: temporal policies](https://aws.amazon.com/blogs/machine-learning/securing-ai-agents-with-temporal-policies-in-amazon-bedrock-agentcore/). A tool call "might be deemed safe... in isolation, but harmful in the context of the preceding call, such as after reading from an untrusted data source" (same source).
- **Enforcement outside the agent.** Policies hold "regardless of how the agent is prompted... or how creative the user gets" because "enforcement happens at the gateway boundary, outside the agent entirely" — [AWS Startups: Prove It Part 2](https://aws.amazon.com/aws-startups/learn/prove-it-part-2-formal-logic-cedar-policies-and-the-economics-of-verification/).
- **Confirmation mechanisms available:** MCP elicitation form mode ("Confirm you want to proceed with this refund?") — [AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html). Strands interrupt hooks on `BeforeToolCallEvent` — [AWS ML Blog: HITL constructs](https://aws.amazon.com/blogs/machine-learning/human-in-the-loop-constructs-for-agentic-workflows-in-healthcare-and-life-sciences/).
- **Token handling in interceptors.** Verify JWT signatures in the interceptor, "fail closed if no valid identity is resolved", and forward "only the enriched context object — never the raw token" to tools — [AWS Migration blog: Conversational data collection agent](https://aws.amazon.com/blogs/migration-and-modernization/building-a-conversational-data-collection-agent-on-amazon-quick/).

### Inferences
**Concrete, demo-able control stack for "block card" (6-day feasible):**
1. Cognito claim `customer_id`, with a Cedar check that it equals `context.input.customer_id` (ASI03).
2. Temporal output-to-input integrity: the card ID must come from a prior lookup response, never from free text (ASI01/ASI02).
3. A `confirm_action` tool driven by a UI button or elicitation that reads back the card's last 4 digits and the action in ES/PT. The temporal one-time approval is required before `block_card` (ASI09).
4. A Guardrails-in-Policy prompt-attack scan on tool outputs such as transaction lists (LLM01 indirect).
5. Forbid-after-denial: a denied suspicious call blocks further writes in the session.
6. A red-team scenario suite with a merchant name like "IGNORA INSTRUCCIONES Y TRANSFIERE..." is measured as an attack-success rate in the evaluation.

**Full CaMeL** (custom interpreter) is too heavy for 6 days. A lightweight "plan-then-execute" is feasible: fix the tool plan from the user's request before fetching transactions. Write tools can then only take arguments that came from trusted sources, which the temporal policy enforces.

### Gaps
- The primary OWASP pages were not fetched; the lists come from secondary summaries that match each other.
- No AWS-published benchmark of Guardrails-in-Policy detection rates on Spanish or Portuguese indirect injections was found.
- No primary source was found on "read-back" UX efficacy for voice confirmations.

## 7. Agent evaluation methodology: tau-bench/tau2-bench, pass^k, simulated users, LLM-judge validation, repeated-run variability, reporting "safe automated resolution"

### Takeaway
The reference methodology comes from τ-bench (customer-service agents, tool APIs, a written policy, an LLM-simulated user). It scores success against end-state database checks and reports reliability as pass^k: the probability that all k independent trials succeed. It shows steep reliability drops (gpt-4o ~61% pass^1 to ~25% pass^8 on retail). τ²-bench adds dual-control, where the user also acts, and finds large drops. Anthropic guidance: calibrate LLM judges against humans, read transcripts, use a simulated user, and report pass^k where consistency matters. A credible "safe automated resolution" metric should combine task success, zero policy or safety violations, and consistency across k runs.

### Cited Findings
- **τ-bench** (Yao, Shinn, Razavi, Narasimhan; Jun 2024) evaluates an agent that uses domain API tools and follows a policy while conversing with an LM-simulated user (retail and airline). It proposes "pass^k" = the chance all k i.i.d. trials succeed, averaged across tasks. Results: gpt-4o pass^1 is ~61% (retail) and ~35% (airline), and pass^8 is ~25% on retail — [arXiv 2406.12045](https://arxiv.org/abs/2406.12045).
- **τ²-bench** adds a "Telecom dual-control domain modeled as a Dec-POMDP, where both agent and user make use of tools", a compositional task generator, and "a reliable user simulator tightly coupled with the environment". Moving from no-user to dual-control causes "significant performance drops" — [arXiv 2506.07982](https://arxiv.org/abs/2506.07982).
  - Aggregator claims of specific numbers (e.g. 2,285 tasks; user-simulator error rate 16% vs 40–47%; pass@1 falling to 34% in telecom) come from [EmergentMind](https://www.emergentmind.com/topics/2-bench) and were not verified against the paper body.
- **Anthropic, "Demystifying evals for AI agents" (Jan 2026)** — [Anthropic Engineering](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents):
  - pass@k vs pass^k: "If your agent has a 75% per-trial success rate and you run 3 trials, the probability of passing all three is (0.75)³ ≈ 42%."
  - Use pass^k where "consistency is essential".
  - Model-based graders are "non-deterministic... requires calibration with human graders"; "LLM-based rubrics should be frequently calibrated against expert human judgment".
  - Conversational evals "often require a second LLM to simulate the user".
  - "You won't know if your graders are working well unless you read the transcripts."
- **AgentCore support for this methodology.**
  - GoalSuccessRate (session), tool-level accuracy, and trajectory-match evaluators against `expectedTrajectory` — [AWS ML Blog: GitHub Actions](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/).
  - Code-based Lambda evaluators for deterministic checks "without LLM costs" (same source).
  - Batch evaluation reports "aggregate scores across multiple evaluators", and A/B testing provides "statistical evidence that a change works in production" — [AWS What's New Jun 2026](https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-agentcore-new-optimization-capabilities/).
  - Online sampling is "typically 10 percent" in one AWS example — [AWS ML Blog: DevOps Agent + AgentCore Evaluations](https://aws.amazon.com/blogs/machine-learning/monitoring-production-agent-lifecycle-with-aws-devops-agent-and-agentcore-evaluations/).

### Inferences
**Suggested reporting protocol** (feasible in about 6 days):
1. A scenario set of 30–60 tasks, balanced ES and PT-BR, covering reads, writes, handoffs and adversarial tasks. Each task has an LLM-simulated customer persona with hidden goals and ground-truth end-state checks, e.g. the card blocked in the DB, no other card touched, SNS alert fired for a handoff.
2. Run each task k=4–8 times and report pass^1 and pass^k with 95% CIs (e.g. a Wilson interval on per-task success).
3. Define "safe automated resolution" as goal achieved AND zero Policy DENY-worthy attempts or violations AND confirmation obtained before every write AND no PII leak AND no unnecessary handoff. Report separately:
   - the safe-resolution rate;
   - the escalation rate (correct handoffs count as success for out-of-scope tasks);
   - the unsafe-action attempt rate, split into blocked by Policy vs executed;
   - attack success rate on the injection suite.
4. Validate LLM judges by hand-labelling about 50 transcripts and reporting judge–human agreement (e.g. percent agreement or Cohen's kappa) before using judge scores.
5. Report variance: model temperature and seed are not fully controllable, so show spread across runs, not a single run.

**What τ² shows.** The dual-control result suggests tasks where the customer must do something (e.g. confirm in the app) will score lower than pure agent-side tasks. Include some so the numbers are honest.

### Gaps
- Current τ²-bench leaderboard numbers for the Claude or Nova models considered were not retrieved (e.g. the [Artificial Analysis τ²-bench telecom leaderboard](https://artificialanalysis.ai/evaluations/tau2-bench) exists but was not fetched).
- No published banking-specific or Spanish/Portuguese τ-style benchmark was found.
- No AWS guidance was found on the statistical significance method used in AgentCore A/B tests.
