import * as cdk from "aws-cdk-lib"
import { DataStack } from "./data-stack"
import { LedgerLensMainStack } from "./ledgerlens-main-stack"
import { AppConfig, resolveDeployScope } from "./utils/config-manager"

export interface LedgerLensStacks {
  data: DataStack
  /** Absent when only the data stack deploys. */
  main?: LedgerLensMainStack
}

/**
 * Adds the LedgerLens stacks to the app. deploy_scope (config.yaml, or
 * `cdk deploy -c deploy_scope=<scope>`) decides what is built:
 *   full: <stack_name_base>-data, then <stack_name_base> on top of it
 *   data: only <stack_name_base>-data (Aurora DSQL and its load pipeline)
 */
export function buildStacks(app: cdk.App, config: AppConfig, env: cdk.Environment): LedgerLensStacks {
  const scope = resolveDeployScope(config.deploy_scope, app.node.tryGetContext("deploy_scope"))

  const data = new DataStack(app, `${config.stack_name_base}-data`, { config, env })
  if (scope === "data") return { data }

  // The tool Lambdas use the data stack's VPC, roles and host, so data deploys first
  const main = new LedgerLensMainStack(app, config.stack_name_base, { config, data: data.data, env })
  main.addDependency(data)
  return { data, main }
}
