import * as path from "path"
import * as cdk from "aws-cdk-lib"
import * as codebuild from "aws-cdk-lib/aws-codebuild"
import * as dsql from "aws-cdk-lib/aws-dsql"
import * as iam from "aws-cdk-lib/aws-iam"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as s3assets from "aws-cdk-lib/aws-s3-assets"
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"

// Pinned aurora-dsql-loader release; the hash is GitHub's published asset digest
const LOADER_URL =
  "https://github.com/aws-samples/aurora-dsql-loader/releases/download/v3.3.0/aurora-dsql-loader-aarch64-unknown-linux-musl.tar.gz"
const LOADER_SHA256 = "eb7a559f13aa3603704aae0e3e27b4f5e2bd3904ae9e656161df60170ce3dff5"

export interface DataConstructProps {
  config: AppConfig
}

/**
 * Aurora DSQL plus the CodeBuild job that loads the organizer snapshot into it
 * (docs/superpowers/specs/2026-09-29-data-loading-design.md).
 */
export class DataConstruct extends Construct {
  public readonly clusterEndpoint: string
  public readonly clusterArn: string
  public readonly loadProjectName: string

  constructor(scope: Construct, id: string, props: DataConstructProps) {
    super(scope, id)

    const cluster = new dsql.CfnCluster(this, "Cluster", {
      deletionProtectionEnabled: true,
      tags: [{ key: "Name", value: `${props.config.stack_name_base}-dsql` }],
    })
    cluster.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN)
    this.clusterEndpoint = cluster.attrEndpoint
    this.clusterArn = cluster.attrResourceArn

    const stagingBucket = new s3.Bucket(this, "StagingBucket", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    })

    // Created with a generated placeholder; a teammate sets the real JSON once (spec section 4.1)
    const hackathonSecret = new secretsmanager.Secret(this, "HackathonS3", {
      secretName: "ledgerlens/hackathon-s3",
      description: "Organizer S3 read keys for the datathon bucket (JSON). Set manually; never commit.",
    })

    const source = new s3assets.Asset(this, "DataLoadSource", {
      path: path.join(__dirname, "..", "..", "data_load"),
      exclude: ["__pycache__", "*.pyc"],
    })

    const project = new codebuild.Project(this, "DataLoad", {
      projectName: "ledgerlens-data-load",
      description: "Loads the organizer snapshot into Aurora DSQL (python -m data_load run)",
      source: codebuild.Source.s3({ bucket: source.bucket, path: source.s3ObjectKey }),
      environment: {
        buildImage: codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
        computeType: codebuild.ComputeType.LARGE,
      },
      timeout: cdk.Duration.minutes(180),
      environmentVariables: {
        AS_OF: { value: props.config.data.as_of },
        WINDOW_YEARS: { value: String(props.config.data.window_years) },
        DSQL_ENDPOINT: { value: cluster.attrEndpoint },
        TEAM_BUCKET: { value: stagingBucket.bucketName },
        HACKATHON_S3: {
          type: codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
          value: hackathonSecret.secretArn,
        },
      },
      buildSpec: codebuild.BuildSpec.fromObject({
        version: "0.2",
        phases: {
          install: {
            "runtime-versions": { python: "3.12" },
            commands: [
              "pip install --quiet -r requirements.txt",
              `curl --proto '=https' --tlsv1.2 -sSfL -o /tmp/loader.tar.gz ${LOADER_URL}`,
              `echo "${LOADER_SHA256}  /tmp/loader.tar.gz" | sha256sum -c -`,
              "tar -xzf /tmp/loader.tar.gz -C /usr/local/bin aurora-dsql-loader",
              "aurora-dsql-loader load --help",
            ],
          },
          build: {
            commands: [
              // The asset unpacks data_load's contents at the source root; python -m needs the package dir
              "mkdir -p /tmp/src/data_load && cp -r . /tmp/src/data_load/ && cd /tmp/src && python -m data_load run",
            ],
          },
        },
      }),
    })

    stagingBucket.grantReadWrite(project)
    hackathonSecret.grantRead(project)
    project.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["dsql:DbConnectAdmin"],
        resources: [cluster.attrResourceArn],
      })
    )
    this.loadProjectName = project.projectName
  }
}
