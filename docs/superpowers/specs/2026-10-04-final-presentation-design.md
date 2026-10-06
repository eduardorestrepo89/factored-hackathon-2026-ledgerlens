# LedgerLens final presentation (Factored Hackathon 2026): design

## Goal

A six-slide HTML deck for the hackathon final. It frames the contact center as a cost problem, shows LedgerLens as the answer, proves the engineering scope and architecture, and closes on the savings per contact with sourced numbers.

## Deliverable

- `docs/hackathon_final_doc/ledgerlens-final.html`: one self-contained file. Plain HTML, CSS and JS, no frameworks. Fonts come from Google Fonts only.
- `docs/hackathon_final_doc/ledgerlens-pitch.html` stays unchanged.
- English. At most 6 slides.

## Shell (reused from `docs/hackathon_final_doc/ledgerlens-pitch.html`)

- **Palette:** `--bg #07081a`, `--ink #161a33`, `--text #f4f6fb`, `--soft #9aa0bb`, `--faint #3a3f5c`. Cobalt (`#2e46e8` / `#6f82ff`) means the AI. Mango (`#f2a31b`) means humans.
- **Fonts:** Funnel Display for headlines, Funnel Sans for body text.
- **Navigation:** → and space advance one step, ← goes back. The counter shows "n / 6". Deep links `#n` and `#n.m` open slide n, optionally at step m.
- **Reveals:** an element with `data-step=n` appears once its slide reaches step n. Motion should explain the content, not decorate it.
- **Source tags.** Every number carries one:
  - **Dataset tag:** "Source: provided contact-center dataset", only for numbers from `docs/agent-handoff/metrics.json`.
  - **Build tag:** "From the LedgerLens build", for numbers from the repo or the AWS account.
  - **Benchmark tag:** "Benchmark: <publisher, year>".
  - **Assumption tag:** "Illustrative assumption".
- No customer PII anywhere in the deck.

## Slide 1: The problem (profitability)

- **Headline:** "A bank has to be profitable, and its contact center is one of its biggest costs."
- **Step 1:** transactional questions are the #1 contact reason. That's 35.0% of 686,296 contacts, about 6,661 a month, 4,663 of them inbound calls. A small bar chart shows contacts by reason, as in deck v2.
- **Step 2:** the #1 complaint is an unrecognized charge. There were 12,297 of them, which is 18.3% of all complaints and 90.6% of transaction complaints. 50.4% came in through the call center, and each took 15.4 days on average to resolve.
- **Step 3:** about 288 agent-hours a month go to these calls (4,663 × 3.7 min), and customers still leave unhappy:
  - transactional NPS −69.9
  - CSAT 2.91 / 4
  - first-contact resolution proxy 70.1%
- **Tags:** dataset (Jun 2023 – Jun 2026, 35 full months). Footnote: the dataset appears synthetic; its NPS answers range only from 2 to 7.

## Slide 2: The solution

- **Headline:** "LedgerLens: your customer's right hand."
- **Three cards** from the pitch:
  - **Hyperpersonalized:** the customer's context is loaded before hello. That context is their cards, charges, open cases, previous contacts and app events.
  - **Intent:** it anticipates why the customer is reaching out and opens with that.
  - **Fraud check:** it protects the customer by blocking the card and opening the claim, only after they tap Yes.
- **Outcome triad** from deck v2: lower cost per contact, higher first-contact resolution, higher satisfaction. Today's values are shown and carry dataset tags; the targets are labelled as goals.
- **Line:** "Credit cards today. Any use case the bank wants tomorrow."

## Slide 3: Technical scope

Two columns plus an "Out of scope" strip.

- **Agentic AI:**
  - prompt engineering
  - tool use
  - short-term memory
  - context window truncation
  - context window compaction (summarization)
  - guardrails
  - model evaluation
- **AI cloud architecture and production:**
  - scalable, highly available services
  - security
  - serverless tools
  - infrastructure as code
  - observability
  - build and ship to production
- **Out of scope:**
  - **Data engineering:** only light cleaning and an ingest pipeline into the database. Data quality issues are known and accepted as is.
  - **Data science / ML:** the intent and fraud models are heuristic mocks. They serve as agent tools and show where the product can scale.
  - **Data analysis:** done but not shipped. A full EDA in the sibling repo `testing-AI-driven-fraud-detection-model` asked whether the model could flag an approved fraud minutes later, during a contact. No variable related to the fraud label: a trial scorecard reached test ROC-AUC 0.46 and PR-AUC 0.0008, equal to the 0.0009 base rate. So the fraud tool is a mock.

## Slide 4: Architecture (animated SVG)

This is a redraw of `docs/architecture-diagram/ledgerlens-architecture.drawio` in the deck's palette, with four lanes revealed left to right:

1. **Channel:** customer → React web chat on Amplify Hosting → Amazon Cognito (OIDC, Authorization Code + PKCE). A Pre-Token Generation V3 Lambda adds the `customer_id` claim.
2. **Agent engine:** AgentCore Runtime running a Strands agent (prompt v10, Yes/No confirmation hook), plus:
   - AgentCore Memory (short-term)
   - the AgentCore Identity token vault
   - Amazon Bedrock models with a Bedrock Guardrail
   - CloudWatch observability
3. **Tools:** AgentCore Gateway (MCP) with a Cedar policy → 9 tool Lambdas. The DB tools run in a VPC with no public IP and reach Aurora DSQL through a VPC endpoint with IAM auth (`ll_read` / `ll_write`). The hand-off Lambda runs outside the VPC and has no DB access.
4. **Data and feedback:** Step Functions → CodeBuild (ingest, transform, curate, load) → S3 → DSQL. Feedback flows API Gateway → Lambda → DynamoDB.

Footer: "Everything deployed as code with AWS CDK." Each node carries a `data-node` name (not an `id`, so slide 5 can clone the SVG without duplicate ids) so slide 5 can highlight it.

## Slide 5: Technical solution

A numbered walkthrough of one chat turn. A copy of the slide 4 diagram fills the width of the slide so it stays readable, and each step highlights its matching nodes. Under the diagram, the five step titles sit in one row, and only the current step's detail shows beneath them.

1. **Sign-in.** The React chat signs the customer in with Cognito over OIDC, and the token goes with every call to the agent's invocation entry point.
2. **Session.** AgentCore Runtime validates the token and opens the session:
   - short-term memory
   - context window optimization: truncation (30-message sliding window, active) and compaction (summarization, built and switchable by config)
   - Bedrock models: DeepSeek v3.2 is deployed, and Claude Sonnet 4.5 and Haiku 4.5 can be swapped in by config
   - Guardrail on input and output
3. **Tool calls.** For every tool call the agent presents a Cognito token from the Identity token vault to the MCP Gateway. The Cedar policy approves the call only when:
   - the token carries a linked `customer_id`
   - the call is about that same customer
   - for block and claim, the customer confirmed
4. **Tools:**

   | Group | Tools |
   |---|---|
   | Session start | `get_session_context`, `classify_call_type` |
   | Cards and charges | `list_credit_cards`, `list_card_transactions`, `explain_transaction` |
   | Fraud | `transaction_fraud_detection` |
   | Actions | `block_credit_card`, `open_claim`, `human_agent_hand_off` |

   Each action runs only after the customer taps Yes.
5. **Badges:**
   - **"Mock models":** intent (`classify_call_type`) and fraud (`transaction_fraud_detection`) are heuristic rules that simulate a model's decision. They were deliberately out of scope.
   - **"Simulated":** the hand-off is a web simulation that triggers a human-agent hand-off.

## Slide 6: Profitability

**Headline:** "Your contact center is expensive. Keep it low, and increase your margins."

1. **Human cost per contact.** The LATAM figure leads as the conservative case, and the global figure appears as a reference line.

   | Figure | Value | How it's derived | Tag |
   |---|---|---|---|
   | LATAM bank transactional call | USD 1.23 (range 0.75–1.55) | $16/hr fully loaded Colombia rate (FusionCX 2026, $12–20/hr) × 3.7 min handle time (dataset) ÷ 0.8 occupancy (assumption) | benchmark + assumption |
   | Global reference | USD 7.20 per inbound call | ContactBabel, 2026 US Contact Center Decision-Makers' Guide. Gartner's 2019 figure of $8.01 per live contact supports it. | benchmark |

2. **LedgerLens cost per contact** at 6,661 contacts a month, one bar per model, split into tokens, Guardrail, variable infra and fixed infra.

   | Model | Tokens | Guardrail | Variable infra | Fixed infra | **Total** |
   |---|---|---|---|---|---|
   | DeepSeek v3.2 (deployed) | 0.0554 | 0.0072 | 0.0322 | 0.0038 | **0.099** |
   | Claude Haiku 4.5 | 0.1134 | 0.0072 | 0.0322 | 0.0038 | **0.157** |
   | Claude Sonnet 4.5 | 0.3401 | 0.0072 | 0.0322 | 0.0038 | **0.383** |

3. **The gap.** Savings per contact and per month, counting up as they appear.

   | Model | Saved vs LATAM $1.23 | Saved vs global $7.20 | Saved per month, LATAM / global |
   |---|---|---|---|
   | DeepSeek v3.2 | $1.13 (92%) | $7.10 (99%) | $7,536 / $47,302 |
   | Haiku 4.5 | $1.07 (87%) | $7.04 (98%) | $7,150 / $46,916 |
   | Sonnet 4.5 | $0.85 (69%) | $6.82 (95%) | $5,640 / $45,406 |

   The monthly figures use the unrounded per-contact totals and are shown in whole dollars, so each tooltip's subtraction matches its cell.

   - **Big average savings:** two large figures under the cards, readable from the back of the room. They show the per-contact saving averaged over the three models: **83%** vs LATAM ((92.0% + 87.3% + 68.8%) ÷ 3 = 82.7%) and **97%** vs the global reference ((98.6% + 97.8% + 94.7%) ÷ 3 = 97.0%). Each has a tooltip with its calculation.
   - **Caveat line:** these figures assume a fully automated contact. A contact handed off to a person still costs a human contact.
   - **Closing:** "LedgerLens. Every customer, understood."

### Cost tooltips (required)

Every cost figure on slide 6 shows a tooltip on mouse-over explaining how it was calculated. That covers each human benchmark, each model's bar and total, and each savings figure. Keyboard focus also shows the tooltip, so it works when presenting. The tooltips hold:

- **LATAM human:** the formula ($16/hr × 3.7 min ÷ 0.8 = $1.23), the $12–20/hr range, the FusionCX 2026 source, and the occupancy assumption. Note that the 2.0 min wait time is excluded because it costs the customer's time, not the agent's.
- **Global human:**
  - the ContactBabel 2026 source
  - the Gartner 2019 $8.01 figure in support
  - a note that published benchmarks include longer calls, after-call work and overhead
- **Each model total:** shows the following.
  - **Session:** one contact is a 9-turn session with 12 model calls and 7 tool calls.
  - **Tokens:**
    - DeepSeek uses about 85.2K input and 1.4K output tokens. Claude uses about 95.5K input and 1.5K output tokens.
    - The us-east-1 on-demand prices per 1M tokens are DeepSeek $0.62 / $1.85, Haiku $1.10 / $5.50 and Sonnet $3.30 / $16.50.
    - These are calibrated on Bedrock CloudWatch token metrics from the account, and the unit prices match Cost Explorer.
  - **Caching:** prompt caching would bring Haiku to about $0.091 and Sonnet to about $0.186. Bedrock offers no caching for DeepSeek.
- **Guardrail:** 2 ApplyGuardrail calls per model call, content and topic policies, $0.15 per 1K text units, so $0.0006 per model call.
- **Variable infra ($0.0322):**
  - Cognito M2M tokens $0.0203
  - AgentCore Runtime $0.0089
  - DSQL DPUs $0.0014
  - Memory, Gateway, Cedar, Lambda and logs about $0.0016
- **Fixed infra ($25.54 a month ÷ 6,661):**
  - API Gateway cache $14.60
  - DSQL VPC endpoint $7.30
  - DSQL storage $1.58
  - Secrets $1.20
  - DSQL background $0.81
  - ECR / Amplify $0.05
  - The one-off data pipeline is excluded.
- **Savings:** the subtraction behind each figure, and the volume of 6,661 transactional contacts a month (dataset).

The sources (pricing pages and benchmark URLs) are listed in a collapsible "Sources" note at the foot of slide 6.

## Verification

- Open the file in Chrome. Step through all 6 slides with → and ←, and check the `#n.m` deep links and that no console errors appear.
- Check every number against `metrics.json` or the cost tables above.
- Hover over and focus each slide 6 cost figure and check its tooltip.
- Check the layout at 1920×1080 and 1366×768. A phone-width layout must not scroll horizontally.

## Out of scope

- Changes to the deployed system: enabling summarization, caching the M2M token, removing the API Gateway cache.
- A live demo inside the deck.
- Speaker notes.
