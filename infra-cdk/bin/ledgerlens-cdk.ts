#!/usr/bin/env node
import * as cdk from "aws-cdk-lib"
import { buildStacks } from "../lib/ledgerlens-app"
import { ConfigManager } from "../lib/utils/config-manager"

const config = new ConfigManager("config.yaml").getProps()
const app = new cdk.App()

// deploy_scope full (default) or data; override per run with `cdk deploy -c deploy_scope=data`
buildStacks(app, config, {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION,
})

app.synth()
