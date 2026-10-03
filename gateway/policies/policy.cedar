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
// 1) A token with a linked customer can use the three LedgerLens read tools.
// 2) No call may be about a different customer than the one in the token.
// Cedar is deny-by-default, so a token with a blank customer_id gets no tools.
//
// SYNTAX NOTES:
// - The Cedar action name format is: "<TargetName>___<tool_name>" (triple underscore).
//   Target names are <slug>-target (backend-construct.ts); tool names come from each
//   tool's tool_spec.json. infra-cdk/test/backend-gateway.test.ts checks both.
// - The cedar-policy custom resource creates one policy per statement.
// - List only tools whose Gateway targets are deployed: CreatePolicy fails on an
//   action whose target doesn't exist.
// - Comment lines must start with //; CDK strips them before CreatePolicy.
//
// {{GATEWAY_ARN}} is replaced by CDK at deploy time with the actual Gateway ARN.
//
// TO CHANGE THE POLICY:
// Edit this file, then run `cdk deploy` to apply.

// 1) A signed-in customer can use the LedgerLens read tools. A blank customer_id
//    means the login isn't linked to a customer, so no tools.
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"list-credit-cards-target___list_credit_cards",
    AgentCore::Action::"list-card-transactions-target___list_card_transactions",
    AgentCore::Action::"get-session-context-target___get_session_context"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when { principal.hasTag("customer_id") && principal.getTag("customer_id") != "" };

// 2) No call may be about a different customer than the one in the token.
forbid(
  principal is AgentCore::OAuthUser,
  action,
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  context has input && context.input has customer_id &&
  principal.hasTag("customer_id") &&
  context.input.customer_id != principal.getTag("customer_id")
};
