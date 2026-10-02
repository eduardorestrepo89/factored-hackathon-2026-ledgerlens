import * as cdk from "aws-cdk-lib"
import { Construct } from "constructs"
import { DataConstruct } from "./data-construct"
import { AppConfig } from "./utils/config-manager"

export interface DataStackProps extends cdk.StackProps {
  config: AppConfig
}

/**
 * Aurora DSQL with VPC-only access and the pipeline that loads it, in a stack of its
 * own so the database deploys without the agent backend or the frontend:
 *   cdk deploy <stack_name_base>-data
 * Spec: docs/superpowers/specs/2026-10-02-data-pipeline-design.md
 */
export class DataStack extends cdk.Stack {
  public readonly data: DataConstruct

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, {
      ...props,
      description: "LedgerLens data: Aurora DSQL, VPC-only access and the load pipeline",
    })
    this.data = new DataConstruct(this, "Data", { config: props.config })

    new cdk.CfnOutput(this, "DsqlEndpoint", {
      value: this.data.clusterEndpoint,
      description: "Aurora DSQL cluster endpoint",
      exportName: `${props.config.stack_name_base}-DsqlEndpoint`,
    })

    new cdk.CfnOutput(this, "DataLoadProject", {
      value: this.data.loadProjectName,
      description: "CodeBuild project that runs pipeline stages 1-3 (STAGE=ingest|transform|load)",
    })

    new cdk.CfnOutput(this, "DataPipelineStateMachine", {
      value: this.data.stateMachineArn,
      description: "Step Functions data pipeline: ingest, transform, load, read check (make load-data)",
    })

    new cdk.CfnOutput(this, "DsqlPrivateHost", {
      value: this.data.privateHost,
      description: "Aurora DSQL host inside the VPC (DSQL_HOST for the tool Lambdas)",
    })
  }
}
