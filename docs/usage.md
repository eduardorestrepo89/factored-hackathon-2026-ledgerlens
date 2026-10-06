# Usage guide

How to use LedgerLens once it is running: as a customer in the chat, and as the person running a demo who links logins to customers. To deploy it, see [DEPLOYMENT.md](DEPLOYMENT.md). To run the frontend on your machine, see [installation.md](installation.md).

- **Live app:** https://main.dteq5fgkcy7a4.amplifyapp.com
- **Local frontend:** http://localhost:3000, after the steps in [installation.md](installation.md#5-run-the-frontend-locally)

## Signing in

1. Open the app and choose **Iniciar sesión** (*Sign in*). The sign-in screen already has the language selector.
2. Cognito's managed login page opens. Sign in with your email and password.
3. You come back to the chat.

Self sign-up is off: the team creates every login. A login only sees data once its Cognito `sub` is linked to a customer: see [Logins and personas](#logins-and-personas). The sign-out button in the header asks for confirmation first.

## The chat

The header holds:
- **The owner badge:** *Hablas con LedgerLens* while the agent owns the chat.
- **The language selector:** Español, Português or English.
- **The dark mode switch.**
- **Nueva conversación** (*New chat*), enabled once the agent has replied.
- **Sign out.**

**Languages.** The selector changes the interface text. The browser remembers it (`localStorage`); the default is Spanish. The agent answers in the language you write in, whatever the selector says: Spanish, Portuguese or English. When a message is too short to tell, it uses Portuguese for customers in Brazil and Spanish otherwise. The interface strings are in `frontend/src/lib/i18n.tsx`.

**Starting.** Type a message, or pick one of the two suggestions: *No reconozco un cargo de mi tarjeta* (*I don't recognize a charge on my card*) or *¿Por qué rechazaron mi compra?* (*Why was my purchase declined?*). A suggestion is sent in the selected language.

**Tool calls.** Each tool the agent runs shows as a line in plain words, for example *Revisando movimientos* (*Checking transactions*), with a spinner until it finishes. Click it to see the raw data sent and the response.

**Errors.** If a turn fails, a red banner shows *No se pudo obtener respuesta* (*Couldn't get a response*) with a **Reintentar** (*Retry*) button that sends the same message again.

**New chat.** **Nueva conversación** clears the screen and starts a new session id. The agent's memory is per session, so the new chat starts from scratch.

**The bank's "today".** The data is a snapshot, and its "today" is 2026-06-17 (`data.as_of` in `infra-cdk/config.yaml`). The tools count "the last 72 hours" and default date ranges from that date, not from the real one.

## What the agent can do

The agent acts only for the signed-in customer and only through these 9 tools. The three marked *Yes/No* never run until you tap Yes.

| Tool | What it does for you |
|---|---|
| `list_credit_cards` | Lists your cards in every status, by last 4 digits, with balance, limit, available credit, expiry and days past due. |
| `list_card_transactions` | Finds charges by card, dates, merchant (ignoring accents and case), amount or status. Up to 25 per search, newest first. |
| `get_session_context` | Loads your profile, cards, last 72 hours of charges, recent app activity and open cases. Runs by itself at the start of a chat. |
| `classify_call_type` | Ranks up to 3 likely reasons you're contacting the bank, such as a declined charge, a flagged charge or an open case. Runs by itself at the start of a chat. |
| `explain_transaction` | Explains one charge: merchant, amount, place and status; for a decline, what the bank recorded it means; for another currency, the amount in your card's currency at that day's rate; how it compares with your habits on that card. |
| `transaction_fraud_detection` | Asks the bank's fraud engine about one charge, or sweeps a card's last 30 days. The agent never tells you the verdict. It uses it to decide what to ask you. |
| `block_credit_card` | *Yes/No.* Blocks a card at once. It can't be undone from the chat. |
| `open_claim` | *Yes/No.* Opens a fraud or dispute claim for the charges you name, one per card and currency. It gives the claim id and, when the bank has enough history, how many days similar claims usually take. |
| `human_agent_hand_off` | *Yes/No.* Passes the chat to a person with a summary, so you don't repeat anything. |

What each tool takes and returns: [api.md, The 9 tools](api.md#the-9-tools).

### How a chat starts

On the first message of a chat, before the model runs, the agent calls `get_session_context` and `classify_call_type` in parallel (`agent/ledgerlens/tools/session_context.py`). It keeps their results in the session's state and puts them in the system prompt on every turn, so they never drop out of the conversation window. If either call fails, it tries again on the next message.

That is why the first reply can go straight to the point:
- **If your message already says what you need,** the agent answers that.
- **Otherwise** it greets you by first name and asks about the most likely reason, for example a declined purchase at a named merchant. For a flagged or unreviewed charge, it asks whether you recognize it.

It names the event, never how it guessed it, and drops a wrong guess.

### Yes/No before the agent acts

When the agent calls `block_credit_card`, `open_claim` or `human_agent_hand_off`, the call pauses and a card appears in the chat:
- **Block:** *¿Bloqueamos tu tarjeta •••• 4497?* (*Shall we block your card ending 4497?*)
- **Claim:** *¿Abrimos el reclamo?* (*Shall we open the claim?*), with the number of charges.
- **Hand-off:** *¿Te paso con una persona?* (*Shall I pass you to a person?*)

How it works:
- **Only a click on Yes runs the call.** The agent's `ConfirmationHook` (`agent/ledgerlens/tools/confirmation_hook.py`) waits for the answer. For a block or a claim, a Yes also sets the `customer_confirmed` flag that the Gateway's Cedar policy requires, so the model can't fake consent.
- **No cancels it.** The agent is told not to try again unless you ask.
- **The text box is locked while a card is open.** Keyboard focus goes to **No**, the safe choice.
- **A typed reply counts as No.** A client that sends text instead of a click, such as `test-scripts/test-agent.py`, which has no buttons, gets a No. The text reaches the agent as your words, and if you still want the action it calls the tool again and the card shows again.
- **A card block asks for a fingerprint after Yes.** The card shows a 3-second simulated fingerprint check (*Verificando tu identidad…*, *Verifying your identity…*). It always passes; **Cancelar** (*Cancel*) during the check counts as No. It stands in for the bank's real step-up authentication (`frontend/src/components/chat/ConfirmCard.tsx`).
- **A Yes changes the database for real.** A block sets the card to `Blocked` in Aurora DSQL, and a claim inserts a row into `complaints`. Both stay for every later session until the data is reloaded ([DEPLOYMENT.md, Operating the data pipeline](DEPLOYMENT.md#operating-the-data-pipeline)).

### Hand-off to a person

After a Yes on the hand-off:
1. **A ticket appears in the chat:** *Caso HO-XXXXXXXX* (*Case*), the priority, the reason in plain words and the related ids.
2. **The agent says goodbye.** A person continues in this chat, and you won't need to repeat anything.
3. **The screen splits**, a moment after the goodbye finishes. Side by side on a wide window, stacked on a narrow one:
   - **Left: *App del cliente*** (*Customer app*), the customer's phone. Its badge reads *En la cola de Fraudes* (*In the Fraud queue*) for a hand-off with reason `FRAUD_CONFIRMED`, and *En la cola de Servicio general* (*General service*) otherwise.
   - **Right: *Escritorio de Laura*** (*Laura's desk*), the human agent's desk. It shows the case, the assistant's summary, the related ids, what the assistant already told the customer, a live mirror of the conversation, and two suggested replies with a **Usar** (*Use*) button. Under them is a box to write as Laura.
4. **Laura takes over.** Her first message tells the customer she joined, and the header changes to *Hablas con Laura, asesora* (*You're talking to Laura, an advisor*).

What is real and what is demo:
- **The hand-off tool sends nothing anywhere.** It validates the hand-off and returns an id made from its content (`gateway/tools/human_agent_hand_off/`).
- **The desk is part of the same web page** (`frontend/src/components/chat/AgentDesk.tsx`, `frontend/src/lib/handoff.ts`).
- **Laura's messages stay in the browser.** They never reach AgentCore.
- **After the hand-off the agent is never called again** in that chat. Messages typed on the phone show on both sides, but go nowhere else.
- **Nueva conversación ends the split** and starts over.

### Feedback

Each agent reply has thumbs up and thumbs down. Either one opens a dialog for an optional comment of up to 5,000 characters. **Send** stores the rating with the reply's text, the session id and your Cognito `sub` in DynamoDB (`ledgerlens-bank-assistant-feedback`), shows *¡Gracias por tu opinión!* (*Thanks for your feedback!*) and locks both thumbs for that reply. The API is in [api.md, Feedback API](api.md#feedback-api).

### What the agent won't do

Two layers decline requests:

- **The Bedrock guardrail** (`infra-cdk/lib/utils/agent-guardrail.ts`) blocks four denied topics:
  - software and coding;
  - general knowledge and schoolwork;
  - entertainment and lifestyle;
  - politics, religion, legal and medical advice.

  It also blocks harmful content and prompt attacks. A blocked message gets a fixed reply in Spanish, Portuguese and English: *I can only help with your credit cards: your cards, your transactions and charges you don't recognize.*
- **The system prompt** (`agent/ledgerlens/tools/system_prompt.py`) handles banking requests the agent can't serve: new products, limit increases, credit or investment advice, loans and changes to personal data. The agent says so in one sentence and calls the hand-off (reason `OUT_OF_SCOPE`), so a Yes/No card appears. Anything else unrelated to your cards that gets past the guardrail is declined in one sentence, without a hand-off.

It also never:
- shows fraud verdicts, scores, risk flags, internal codes, income or segment;
- shows a decline's raw response code;
- talks about another customer;
- asks for a PIN, CVV, password, one-time code or full card number. If you write one, it tells you not to share it and doesn't repeat it.

## Logins and personas

### How a login reaches a customer's data

The agent's identity chain:
1. The agent takes your Cognito `sub` from your token.
2. It asks Cognito for a Gateway token on your behalf.
3. The V3 pre-token Lambda `ledgerlens-bank-assistant-pretoken-v3` looks your `sub` up in its environment variable `USER_CUSTOMER_IDS_MAP` and adds the matching `customer_id` claim, or a blank one.
4. The agent passes that `customer_id` on every tool call, and the Gateway's Cedar policy refuses any call without one or with a different one.

So a login that isn't in the map can sign in and chat, but the agent can't see any card. It says the account isn't linked yet.

The committed map, in `infra-cdk/lib/cognito-construct.ts`, holds 15 real subs:

| Login | Linked to | Who uses it |
|---|---|---|
| `demo@ledgerlens.example` | P03 by default, switchable | The team, for demos |
| `eval-p01@ledgerlens.example` … `eval-p10@ledgerlens.example`, 8 logins: P01, P03, P04, P05, P06, P07, P09, P10 | Their own persona, fixed | The eval harness. They are in the Cognito group `evaluators`, which may also switch the model and base prompt per session ([api.md, Evaluation override](api.md#evaluation-override)). |
| `judge-1@ledgerlens.example` … `judge-5@ledgerlens.example`: P07, P09, P05, P08, P04 | Their own persona, fixed | The hackathon judges, one use case each ([docs/evaluation/judges.md](evaluation/judges.md)). Not in `evaluators`, so always the production model and prompt. |
| One more login | P07's alternate customer, `CLI-HTX9ITCO0IMR` | Added with the judge logins |

The demo password is shared within the team, never in git. The evaluation and judge passwords are in `evals/.env` (gitignored), written by `evals/eval_users.py`. Two people on the same login see each other's changes: card blocks and claims are real writes.

### Create the demo login

Only for a new deployment: the current one already has it. Run it in bash (Git Bash on Windows). The password needs 8+ characters with upper, lower, digit and symbol.

```bash
export AWS_PROFILE=ledgerlens
POOL_ID=$(aws cloudformation describe-stacks --stack-name ledgerlens-bank-assistant \
  --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" --output text)
read -rsp "Demo password: " DEMO_PASSWORD; echo
aws cognito-idp admin-create-user --user-pool-id "$POOL_ID" --username demo@ledgerlens.example \
  --user-attributes Name=email,Value=demo@ledgerlens.example Name=email_verified,Value=true \
  --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id "$POOL_ID" \
  --username demo@ledgerlens.example --password "$DEMO_PASSWORD" --permanent
SUB=$(aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username demo@ledgerlens.example \
  --query "UserAttributes[?Name=='sub'].Value" --output text)
echo "$SUB"
```

Then add `"<SUB>": "CLI-70U0WJ1NH1MN"` (P03) to `USER_CUSTOMER_IDS_MAP` in `infra-cdk/lib/cognito-construct.ts`, commit it and redeploy the main stack ([DEPLOYMENT.md, Updating](DEPLOYMENT.md#updating)). Until that deploy, the new login is unlinked; link it for now with `set_persona` below, knowing that any deploy made before the commit unlinks it again.

### Switch the demo login's persona

To switch the demo login to another customer, change its entry in the Lambda's `USER_CUSTOMER_IDS_MAP`. Either edit it in the Lambda console (`ledgerlens-bank-assistant-pretoken-v3` → Configuration → Environment variables), or use this function. It reads the current map and changes only the demo login's entry:

```bash
export AWS_PROFILE=ledgerlens
POOL_ID=$(aws cloudformation describe-stacks --stack-name ledgerlens-bank-assistant \
  --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" --output text)
SUB=$(aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username demo@ledgerlens.example \
  --query "UserAttributes[?Name=='sub'].Value" --output text)

set_persona() {  # usage: set_persona <customer_id>
  local fn=ledgerlens-bank-assistant-pretoken-v3 map
  map=$(aws lambda get-function-configuration --function-name "$fn" \
    --query "Environment.Variables.USER_CUSTOMER_IDS_MAP" --output text)
  aws lambda update-function-configuration --function-name "$fn" \
    --cli-input-json "$(python -c 'import json, sys; m = json.loads(sys.argv[1]); m[sys.argv[2]] = sys.argv[3]; print(json.dumps({"Environment": {"Variables": {"USER_CUSTOMER_IDS_MAP": json.dumps(m, sort_keys=True)}}}))' "$map" "$SUB" "$1")" \
    --query "Environment.Variables.USER_CUSTOMER_IDS_MAP" --output text
  aws lambda wait function-updated --function-name "$fn"
}
set_persona CLI-50OIF5EIYSWK   # P05
```

- **Merge, don't replace.** `update-function-configuration` replaces the Lambda's whole environment. The older version of this function set the map to the demo login alone, which unlinked every other login. This one keeps them.
- **The switch takes effect on the next message:** the agent asks for a new Gateway token on every request.
- **Start a new chat after every switch.** The old chat keeps the previous persona: its session context (name, cards, likely reasons) was saved with the session at its first message, and its memory holds the earlier answers.
- **Don't switch during an evaluation run.** The evaluation rules forbid editing the map while a run is going ([evals/README.md](../evals/README.md#rules)).
- **Who can switch:** only someone with AWS credentials for the `ledgerlens` account that may update that Lambda. The person chatting never can. Evaluation logins can switch the model, not the customer.
- **A redeploy resets the map.** The next deploy of the main stack sets it back to the committed `USER_CUSTOMER_IDS_MAP`: the subs above, with the demo login on P03. A sub that exists only in the console is lost.

### Evaluation and judge logins

`python -m evals.eval_users create --apply` creates the 8 logins, saves their passwords to `evals/.env` and writes their subs into `cognito-construct.ts`. After the deploy that creates the `evaluators` group, `python -m evals.eval_users add-to-group --apply` adds them. Without `--apply` both commands only list what they would do. Setup and the evaluation rules: [evals/README.md](../evals/README.md).

`python -m evals.eval_users create-judges --apply` does the same for the 5 judge logins (`JUDGES` in `evals/config.py`), with passwords saved as `JUDGE_PASSWORD_J1` … `J5`. It never adds them to the `evaluators` group. What each judge should try: [docs/evaluation/judges.md](evaluation/judges.md).

### Personas

The 10 demo personas are real customers in the curated data (`data_load/personas.json`, "today" 2026-06-17). The expected outcomes come from `personas.json` and the system prompt.

| Persona | Customer id | Use case | Eval login | What to expect |
|---|---|---|---|---|
| P01 | `CLI-1GL7QBDG3QG0` | Decline explained | yes | `explain_transaction` returns the decline's recorded meaning. The agent says what it means, without the code and without guessing a cause. |
| P02 | `CLI-7EC6UCDZMSKV` | Pending charge | no | Explains that the charge is pending. |
| **P03 (default)** | `CLI-70U0WJ1NH1MN` | Reversed charge with app context | yes | The demo login's committed persona. The session opens with the app signal and explains the reversal. |
| P04 | `CLI-N4FPJIEGD917` | Which card? | yes | Two cards: the agent asks which one before anything else. |
| P05 | `CLI-50OIF5EIYSWK` | Portuguese persona, foreign charge | yes | Answers in Portuguese and explains the charge made in Brazil. |
| P06 | `CLI-PV0OIEA8DAAE` | Limit increase (out of scope) | yes | Declines in one sentence and calls the hand-off (`OUT_OF_SCOPE`), so a Yes/No card appears. |
| P07 | `CLI-EX6BOAOEFZHQ` | Suspected fraud | yes | The fraud flow: asks whether you recognize the charge, offers to block card 4497, reviews its recent charges, opens a fraud claim. A Yes really blocks the card (and opens the claim) until the data is reloaded. Meanwhile, the eval runner's P07 precheck fails. |
| P08 | `CLI-GG3Z1440277M` | Open unrecognized-charge case | no | Follows up the open case without opening a duplicate claim, then hands off. |
| P09 | `CLI-UBR2NCZWTD4K` | Records contradict | yes | `explain_transaction` returns `contradicts_card_state: true` (code 54, "expired card", on a card that isn't expired). The agent says the records don't match and hands off (`UNRESOLVED`). |
| P10 | `CLI-Z3V3SBS18YWQ` | Card not active | yes | Gives the card's Blocked status without guessing why (the data has no reason). If you ask why, it hands off. |

P02 and P08 have no evaluation login: switch the demo login to them.

## Smoke scripts

They check the deployed stack without the browser. Run them from the repo root in bash, with `AWS_PROFILE=ledgerlens`. `uv` installs their dependencies on the fly from `test-scripts/requirements.txt`. `$SUB` is a login's Cognito sub; the commands in [Switch the demo login's persona](#switch-the-demo-logins-persona) set it to the demo login's.

```bash
export AWS_PROFILE=ledgerlens
run() { uv run --no-project --with-requirements test-scripts/requirements.txt python "$@"; }

run test-scripts/test-gateway.py --user-sub "$SUB"                                 # list the tools this login gets
run test-scripts/test-gateway.py --user-sub "$SUB" --customer-id CLI-70U0WJ1NH1MN  # call list_credit_cards
run test-scripts/test-agent.py                                                      # chat with the deployed agent
```

**`test-gateway.py`** calls the Gateway and Cedar directly, without the agent. It gets a machine token for `--user-sub` the way the agent does, so the pre-token Lambda adds that sub's `customer_id`. Then it lists the tools and, with `--customer-id`, calls `list_credit_cards`.
- **Linked sub with its own customer id:** the call succeeds and prints the cards.
- **Any other customer id:** Cedar refuses the call and the script exits with code 1.
- **A sub that isn't in the map:** tests an unlinked login.

**`test-agent.py`** asks for a username and password and opens an interactive chat with the deployed agent, printing the reply, the tool calls and their results (cut to 200 characters). It shows no Yes/No buttons, so anything you type after a pause counts as No.

`test-feedback-api.py` and `test-memory.py` cover the feedback API and AgentCore Memory: [test-scripts/README.md](../test-scripts/README.md).

## Common errors and fixes

| Symptom | Cause | Fix |
|---|---|---|
| The agent says your account isn't linked, or it can't see your cards; tool calls are refused | The login's `sub` isn't in `USER_CUSTOMER_IDS_MAP`, or a redeploy reset the map to its committed value | Link it with [`set_persona`](#switch-the-demo-logins-persona), and commit the sub to `cognito-construct.ts` so the next deploy keeps it. Check the claim with `test-gateway.py --user-sub <sub> --customer-id <id>`. |
| After a persona switch the agent still uses the old customer's name or cards | The chat's session context and memory are from before the switch | Choose **Nueva conversación**. |
| Sign-in fails with a redirect error, or after signing in you land on the wrong site (Amplify instead of localhost, or the reverse) | `frontend/public/aws-exports.json` is stale: the last `deploy-frontend.py` run wrote the other site's redirect URL, or the stack was recreated | Locally: `AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py --config-only` and restart `npm run dev`. On Amplify: rerun `deploy-frontend.py` without the flag. |
| The local app opened on a port other than 3000 and sign-in fails | Port 3000 was busy, so Vite took the next one; Cognito allows only `http://localhost:3000` | Free port 3000 and restart `npm run dev`. |
| On a fresh clone the local app can't sign in; the browser console says *Failed to load auth configuration* | `frontend/public/aws-exports.json` is generated and gitignored, so a clone has none | Run the `--config-only` step above. |
| A card block says the card is already blocked, or a claim says it already existed | Someone tapped Yes in an earlier session: the write is real | Expected. A data reload restores the cards and claims ([DEPLOYMENT.md](DEPLOYMENT.md#operating-the-data-pipeline)); never reload during a demo. |
| Tools fail with connection or "table does not exist" errors | A data load is running (about 2 minutes without tables) or the cluster was never loaded | Wait for the load to finish; see [DEPLOYMENT.md, Troubleshooting](DEPLOYMENT.md#troubleshooting). |
| The reply is the fixed *I can only help with your credit cards…* text | The guardrail blocked the message as off-topic, harmful or a prompt attack | Ask about your cards or charges. |
