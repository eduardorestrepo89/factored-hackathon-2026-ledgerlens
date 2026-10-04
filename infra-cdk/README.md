# Fullstack AgentCore Solution Template - Infrastructure

This directory contains the AWS CDK infrastructure code for deploying the Fullstack AgentCore Solution Template.

## Prerequisites

- Node.js 18+
- AWS CLI configured with appropriate credentials
- AWS CDK CLI installed: `npm install -g aws-cdk`

## Minimal IAM Policy for Deployment

The file `minimal-deploy-policy.json` contains the minimum IAM permissions required to deploy this CDK application. This policy includes 30 actions across 7 statements covering CloudFormation, S3, SSM, ECR, IAM PassRole, and Amplify.

**Important:** This policy assumes CDK bootstrap has already been run in the target account. It does not include permissions for `cdk bootstrap`. To bootstrap a fresh account, you'll need additional IAM permissions (CreateRole, AttachRolePolicy, PutRolePolicy, etc.) - refer to the AWS CDK Bootstrap documentation for details.

**Security Note:** Some wildcards are present for resources (e.g., `arn:aws:cloudformation:*:*:stack/*`). For production environments, replace these with your specific resource ARNs to further scope down permissions.

## Getting Started

All of the following commands assuming you are in the top of the `infra-cdk/` directory
### Install Dependencies

```bash
npm install
```

### Build TypeScript

```bash
npm run build
```

### Bootstrap CDK (First Time Only)

```bash
npx cdk bootstrap
```

### Deploy

```bash
npx cdk deploy --all
```

`deploy_scope` in `config.yaml` decides what that deploys:

- `full` (default): `<stack_name_base>-data` (Aurora DSQL and its load pipeline), then
  `<stack_name_base>` (Amplify, Cognito, the agent, the Gateway and the tool Lambdas).
- `data`: only `<stack_name_base>-data`.

Override it for one run with `npx cdk deploy --all -c deploy_scope=data`.

## Useful Commands

* `npm run build`   - Compile TypeScript to JavaScript
* `npm run watch`   - Watch for changes and compile automatically
* `npm run test`    - Run Jest unit tests
* `npx cdk deploy --all` - Deploy all stacks to your AWS account/region
* `npx cdk diff`    - Compare deployed stack with current state
* `npx cdk synth`   - Emit the synthesized CloudFormation template
* `npx cdk destroy --all` - Remove all deployed resources

## Configuration

Edit `config.yaml` to customize your deployment:

```yaml
stack_name_base: "fullstack-agentcore-solution-template"

frontend:
  domain_name: null  # Optional: Set to your custom domain
  certificate_arn: null  # Optional: Set to your ACM certificate ARN

backend:
  pattern: "ledgerlens"  # Agent folder under agent/
```

## Project Structure

```
infra-cdk/
├── bin/
│   └── ledgerlens-cdk.ts         # CDK app entry point
├── lib/
│   ├── ledgerlens-app.ts         # Builds the stacks for deploy_scope
│   ├── ledgerlens-main-stack.ts  # Main stack: Amplify, Cognito, backend
│   ├── backend-construct.ts      # AgentCore Runtime, Gateway and tool Lambdas
│   ├── data-stack.ts             # Data stack: Aurora DSQL and its load pipeline
│   ├── data-construct.ts
│   └── utils/                    # Utility functions and constructs
├── test/
│   └── ledgerlens-cdk.test.ts    # deploy_scope tests
├── cdk.json                 # CDK configuration
├── config.yaml              # Application configuration
├── package.json
└── tsconfig.json
```

## Development Workflow

1. Make changes to TypeScript files in `lib/`
2. Run `npm run build` to compile
3. Run `npx cdk diff` to see what will change
4. Run `npx cdk deploy --all` to deploy changes

For faster iteration, use watch mode:
```bash
npm run watch
```

## Deployment Details

The CDK deployment creates multiple stacks with a specific deployment order:

### Stack Architecture & Deployment Order

1. **Cognito Stack** (CognitoStack):
   - Cognito User Pool for user authentication (ESSENTIALS tier for V3 Pre-Token Lambda)
   - User Pool Client for frontend OAuth flows
   - User Pool Domain for hosted UI
   - V3 Pre-Token Lambda for injecting user identity claims into M2M tokens

2. **Backend Stack** (BackendStack):
   - **Machine Client & Resource Server**: OAuth2 client credentials for service-to-service auth
   - **AgentCore Gateway**: API gateway for tool integration with Lambda targets
   - **AgentCore Runtime**: Bedrock AgentCore runtime for agent execution
   - **Supporting Resources**: IAM roles, DynamoDB tables, API Gateway for feedback

3. **Amplify Hosting Stack** (AmplifyHostingStack):
   - Amplify app for frontend hosting
   - Branch configuration for deployments
   - Custom domain setup (if configured)

### Component Dependencies

Within the Backend Stack, components are created in this order:
1. **Cognito Integration**: Import user pool from Cognito stack
2. **Machine Client**: Create OAuth2 client for M2M authentication
3. **Gateway**: Create AgentCore Gateway, Cedar Policy Engine, and Cedar Policy (depends on machine client)
4. **Runtime**: Create AgentCore Runtime (independent of gateway)

This order ensures authentication components are available before services that depend on them, while keeping the runtime deployment separate since it doesn't directly depend on the gateway.

### Docker Build Configuration

The agent container builds use a specific configuration to handle the repository structure efficiently:

#### Build Context Strategy

The Docker build context is the repository root, so the Dockerfile at `agent/ledgerlens/Dockerfile` can copy the shared `agent/utils/` package next to the agent code.

#### Docker Context Optimization

**Issue**: Large build contexts (including `node_modules/`, `.git/`, etc.) cause Docker builds to hang during the "transferring context" phase, especially in CDK deployments.

**Solution**: `.dockerignore` file at repository root excludes:
- `node_modules/` directories (frontend and infra)
- `.git/` version control data  
- Build artifacts (`cdk.out/`, `.next/`, `dist/`)
- Cache directories (`.ruff_cache/`, `__pycache__/`)

**Result**: Build context reduced from ~100MB+ to ~10MB, eliminating hang issues.

#### Image Contents

The Dockerfile installs `agent/ledgerlens/requirements.txt`, then copies only what the agent imports:

- `agent/ledgerlens/ledgerlens_agent.py` (entry point)
- `agent/ledgerlens/tools/` → `tools/`
- `agent/utils/` → `utils/`

### Key Resources Created

1. **Backend Stack**: 
   - Cognito User Pool integration and machine client
   - AgentCore Gateway with Lambda tool targets
   - AgentCore Runtime for agent execution
   - ECR repository for agent container images
   - CodeBuild project for container builds
   - DynamoDB table for application data
   - API Gateway for feedback endpoints
   - IAM roles and policies

2. **Amplify Hosting Stack**:
   - Amplify app for frontend deployment
   - Automatic builds from Git branches
   - Custom domain and SSL certificate integration
   - Environment-specific deployments

## Troubleshooting

### Build Errors

If you encounter TypeScript compilation errors:
```bash
npm run build
```

### Deployment Failures

Check CloudFormation events in the AWS Console for detailed error messages.

### Clean Build

If you need to start fresh:
```bash
rm -rf node_modules cdk.out
npm install
npm run build
```

## Testing

Run unit tests:
```bash
npm test
```

## Learn More

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [AWS CDK TypeScript Reference](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-construct-library.html)
- [Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock/)
