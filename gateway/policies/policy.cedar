// Cedar policy for AgentCore Gateway tool access control (LedgerLens v1).
//
// HOW IT WORKS:
// The Gateway's JWT Authorizer maps machine-token claims to Cedar principal tags.
// The V3 Pre-Token Lambda (infra-cdk/lambdas/pretoken-v3) adds a customer_id claim:
// the LedgerLens customer linked to the signed-in user, or "" when there is none.
//   JWT claim "customer_id" → principal.getTag("customer_id")
// On tools/call, context.input holds the tool's arguments, so Cedar compares the
// customer_id the agent passed with the one in the token.
//
// RULES:
// 1) A token with a linked customer can use the LedgerLens tools.
// 2) No call may be about a different customer than the one in the token.
// 3) block_credit_card and open_claim need customer_confirmed set to true.
// Cedar is deny-by-default, so a token with a blank customer_id gets no tools.
//
// SYNTAX NOTES:
// - The Cedar action name format is: "<TargetName>___<tool_name>" (triple underscore).
//   Target names are <slug>-target, except fraud-detection-target, which keeps the
//   model-facing tool name within 64 characters (backend-construct.ts); tool names
//   come from each tool's tool_spec.json. infra-cdk/test/backend-gateway.test.ts
//   checks both.
// - The cedar-policy custom resource creates one policy per statement.
// - List only tools whose Gateway targets are deployed: CreatePolicy fails on an
//   action whose target doesn't exist.
// - Comment lines must start with //; CDK strips them before CreatePolicy.
//
// {{GATEWAY_ARN}} is replaced by CDK at deploy time with the actual Gateway ARN.
//
// TO CHANGE THE POLICY:
// Edit this file, then run `cdk deploy` to apply.

// 1) A signed-in customer can use the LedgerLens tools. A blank customer_id
//    means the login isn't linked to a customer, so no tools.
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"list-credit-cards-target___list_credit_cards",
    AgentCore::Action::"list-card-transactions-target___list_card_transactions",
    AgentCore::Action::"get-session-context-target___get_session_context",
    AgentCore::Action::"fraud-detection-target___transaction_fraud_detection",
    AgentCore::Action::"explain-transaction-target___explain_transaction",
    AgentCore::Action::"classify-call-type-target___classify_call_type",
    AgentCore::Action::"block-credit-card-target___block_credit_card",
    AgentCore::Action::"open-claim-target___open_claim",
    AgentCore::Action::"human-agent-hand-off-target___human_agent_hand_off"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when { principal.hasTag("customer_id") && principal.getTag("customer_id") != "" };

// 2) No call may be about a different customer than the one in the token.
//    The actions are listed: AgentCore rejects a forbid over all actions as
//    "Overly Restrictive", because it would also cover tools that don't exist yet.
//    Every listed tool requires customer_id, so no `has` guards are needed.
forbid(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"list-credit-cards-target___list_credit_cards",
    AgentCore::Action::"list-card-transactions-target___list_card_transactions",
    AgentCore::Action::"get-session-context-target___get_session_context",
    AgentCore::Action::"fraud-detection-target___transaction_fraud_detection",
    AgentCore::Action::"explain-transaction-target___explain_transaction",
    AgentCore::Action::"classify-call-type-target___classify_call_type",
    AgentCore::Action::"block-credit-card-target___block_credit_card",
    AgentCore::Action::"open-claim-target___open_claim",
    AgentCore::Action::"human-agent-hand-off-target___human_agent_hand_off"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("customer_id") &&
  context.input.customer_id != principal.getTag("customer_id")
};

// 3) Blocking a card or opening a claim needs the customer's explicit confirmation
//    (write tools spec section 10). The `has` guard matters: a missing argument would
//    make this forbid fail to evaluate, and Cedar skips a forbid that fails, so the
//    call would be allowed.
forbid(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"block-credit-card-target___block_credit_card",
    AgentCore::Action::"open-claim-target___open_claim"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  !(context.input has customer_confirmed) ||
  context.input.customer_confirmed != true
};
