import * as fs from "fs"
import * as path from "path"
import * as yaml from "yaml"

const MAX_STACK_NAME_BASE_LENGTH = 35

export type DeploymentType = "docker" | "zip"

/**
 * What `cdk deploy` builds.
 * - full: the data stack and the main stack (frontend, Cognito, agent, Gateway and tool Lambdas).
 * - data: only the data stack (Aurora DSQL and its load pipeline).
 */
export type DeployScope = "full" | "data"
const DEPLOY_SCOPES: readonly string[] = ["full", "data"]

/**
 * The scope to deploy: a `cdk deploy -c deploy_scope=<scope>` override wins over config.yaml.
 * Context values arrive as raw strings, so the override is validated here.
 */
export function resolveDeployScope(configured: DeployScope, override?: unknown): DeployScope {
  if (override === undefined) return configured
  if (typeof override !== "string" || !DEPLOY_SCOPES.includes(override)) {
    throw new Error(`Invalid -c deploy_scope '${override}'. Must be 'full' or 'data'.`)
  }
  return override as DeployScope
}

/**
 * Network mode for the AgentCore Runtime.
 * - PUBLIC: Runtime is accessible over the public internet (default).
 * - VPC: Runtime is deployed into a user-provided VPC for private network isolation.
 */
export type NetworkMode = "PUBLIC" | "VPC"

/**
 * VPC configuration for deploying the AgentCore Runtime into an existing VPC.
 * Required when network_mode is "VPC".
 */
export interface VpcConfig {
  /** The ID of the existing VPC to deploy into (e.g. "vpc-0abc1234def56789a"). */
  vpc_id: string
  /** List of subnet IDs within the VPC where the runtime will be placed. */
  subnet_ids: string[]
  /** Optional list of security group IDs. If omitted, a default security group is created. */
  security_group_ids?: string[]
}

export interface AppConfig {
  stack_name_base: string
  /** Full deploy or only the data stack. Defaults to "full". */
  deploy_scope: DeployScope
  admin_user_email?: string | null
  backend: {
    pattern: string
    deployment_type: DeploymentType
    /** Name for the agent runtime. Valid characters: a-z, A-Z, 0-9, _. Defaults to "LedgerLensAgent". */
    agent_name: string
    /** Network mode for the AgentCore Runtime. Defaults to "PUBLIC". */
    network_mode: NetworkMode
    /** VPC configuration. Required when network_mode is "VPC". */
    vpc?: VpcConfig
    /**
     * Enable long-term memory (SemanticMemoryStrategy) for the agent.
     * When true, the agent extracts and retrieves facts across sessions.
     * This incurs additional costs: $0.75/1,000 records stored + $0.50/1,000 retrievals.
     * Defaults to false.
     */
    use_long_term_memory: boolean
    /**
     * Number of facts to retrieve per turn when long-term memory is enabled.
     * Maps to the top_k parameter of RetrievalConfig. Defaults to 10.
     */
    ltm_top_k: number
    /**
     * Minimum similarity threshold for long-term memory retrieval.
     * Maps to the relevance_score parameter of RetrievalConfig. Defaults to 0.3.
     */
    ltm_relevance_score: number
    /**
     * Short-term memory: how many recent messages the agent sends to the model per
     * turn. Counts messages, not turns. Integer from 2 to 200. Defaults to 30.
     */
    stm_window_size: number
    /**
     * Summarize the oldest messages once the window is exceeded, instead of dropping
     * them. Each summary costs one extra model call. Defaults to false.
     */
    use_stm_summarization: boolean
    /** Share of messages summarized each time, from 0.1 to 0.8. Defaults to 0.3. */
    stm_summary_ratio: number
    /**
     * Newest messages never summarized. Must be less than stm_window_size when
     * summarization is on. Defaults to 10.
     */
    stm_preserve_recent_messages: number
    /** Model that writes the summaries. Empty (default) means the agent's own model. */
    stm_summarization_model_id: string
    /** System prompt for the summarizer. Empty (default) means the built-in banking prompt. */
    stm_summarization_prompt: string
    /**
     * Discover and auto-connect MCP servers from an AWS Agent Registry.
     * Lightweight: no DynamoDB, no UI, no per-user preferences. Defaults to disabled.
     */
    mcp_registry: McpRegistryConfig
  }
  data: DataConfig
}

/**
 * Runtime MCP-server discovery from an AWS Agent Registry.
 *
 * When enabled, the agent lists the registry's Approved `recordType=MCP`
 * records and auto-connects to each public streamable-HTTP server as a live
 * MCP client. Discovery happens at agent runtime, so no servers are declared
 * at deploy time and no gateway targets are created.
 */
export interface McpRegistryConfig {
  /** Master switch. When false (default) the feature is completely inert. */
  enabled: boolean
  /** ARN or id of the AWS Agent Registry to discover records from. Required when enabled. */
  registry_id: string
}

/** Data settings (docs/superpowers/specs/2026-10-02-data-pipeline-design.md, section 5.3). */
export interface DataConfig {
  /** Bank "today" for the tools: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS, no time zone. */
  as_of: string
}

export class ConfigManager {
  private config: AppConfig

  constructor(configFile: string) {
    this.config = this._loadConfig(configFile)
  }

  private _loadConfig(configFile: string): AppConfig {
    let configPath: string

    // Uses the specified configFile if the file exists
    // otherwise fallsback to existing behavior where the configFile should be
    // named config.yaml and be in the infra-cdk directory. Throws an error if the
    // configFile does not exist and is not the default "config.yaml"
    if (fs.existsSync(configFile)) {
      configPath = configFile
    } else {
      if (path.basename(configFile) !== "config.yaml") {
        throw new Error(`Configuration file '${configFile}' not found.`)
      }
      const defaultConfigPath = path.join(__dirname, "..", "..", configFile) // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      configPath = defaultConfigPath
    }
    if (!fs.existsSync(configPath)) {
      throw new Error(
        `Configuration file ${configPath} does not exist. Please create config.yaml file.`
      )
    }

    try {
      const fileContent = fs.readFileSync(configPath, "utf8")
      const parsedConfig = yaml.parse(fileContent) as AppConfig

      const deploymentType = parsedConfig.backend?.deployment_type || "docker"
      if (deploymentType !== "docker" && deploymentType !== "zip") {
        throw new Error(
          `Invalid deployment_type '${deploymentType}' in ${configPath}. Must be 'docker' or 'zip'.`
        )
      }

      const stackNameBase = parsedConfig.stack_name_base
      if (!stackNameBase) {
        throw new Error(`stack_name_base is required in ${configPath}`)
      }
      if (stackNameBase.length > MAX_STACK_NAME_BASE_LENGTH) {
        throw new Error(
          `stack_name_base '${stackNameBase}' is too long (${stackNameBase.length} chars). ` +
            `Maximum length is ${MAX_STACK_NAME_BASE_LENGTH} characters due to AWS AgentCore runtime naming constraints.`
        )
      }

      const deployScope = parsedConfig.deploy_scope ?? "full"
      if (!DEPLOY_SCOPES.includes(deployScope)) {
        throw new Error(`Invalid deploy_scope '${deployScope}' in ${configPath}. Must be 'full' or 'data'.`)
      }

      // Validate network_mode if provided
      const networkMode = parsedConfig.backend?.network_mode || "PUBLIC"
      if (networkMode !== "PUBLIC" && networkMode !== "VPC") {
        throw new Error(
          `Invalid network_mode '${networkMode}' in ${configPath}. Must be 'PUBLIC' or 'VPC'.`
        )
      }

      // Validate VPC configuration when network_mode is VPC
      const vpcConfig = parsedConfig.backend?.vpc
      if (networkMode === "VPC") {
        if (!vpcConfig) {
          throw new Error(
            `backend.vpc configuration is required in ${configPath} when network_mode is 'VPC'.`
          )
        }
        if (!vpcConfig.vpc_id) {
          throw new Error(
            `backend.vpc.vpc_id is required in ${configPath} when network_mode is 'VPC'.`
          )
        }
        if (!vpcConfig.subnet_ids || vpcConfig.subnet_ids.length === 0) {
          throw new Error(
            `backend.vpc.subnet_ids must contain at least one subnet ID in ${configPath} when network_mode is 'VPC'.`
          )
        }
      }

      // Validate MCP registry discovery configuration.
      // Fail loud: enabling discovery without a registry id is a deploy-time mistake.
      const mcpRegistryEnabled = parsedConfig.backend?.mcp_registry?.enabled === true
      const mcpRegistryId = (parsedConfig.backend?.mcp_registry?.registry_id ?? "").trim()
      if (mcpRegistryEnabled && !mcpRegistryId) {
        throw new Error(
          `backend.mcp_registry.registry_id is required in ${configPath} when backend.mcp_registry.enabled is true.`
        )
      }

      // Validate the bank's "today" for the tools
      const asOf = String(parsedConfig.data?.as_of ?? "2026-06-17T23:59:59")
      if (!/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$/.test(asOf)) {
        throw new Error(
          `data.as_of '${asOf}' in ${configPath} must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.`
        )
      }

      // Validate short-term memory (the agent's conversation window and summarization)
      const stmWindowSize = parsedConfig.backend?.stm_window_size ?? 30
      const useStmSummarization = parsedConfig.backend?.use_stm_summarization === true
      const stmSummaryRatio = parsedConfig.backend?.stm_summary_ratio ?? 0.3
      const stmPreserveRecent = parsedConfig.backend?.stm_preserve_recent_messages ?? 10
      const stmModelId = parsedConfig.backend?.stm_summarization_model_id ?? ""
      const stmPrompt = parsedConfig.backend?.stm_summarization_prompt ?? ""
      if (!Number.isInteger(stmWindowSize) || stmWindowSize < 2 || stmWindowSize > 200) {
        throw new Error(
          `backend.stm_window_size in ${configPath} must be an integer from 2 to 200.`
        )
      }
      if (typeof stmSummaryRatio !== "number" || stmSummaryRatio < 0.1 || stmSummaryRatio > 0.8) {
        throw new Error(`backend.stm_summary_ratio in ${configPath} must be from 0.1 to 0.8.`)
      }
      if (!Number.isInteger(stmPreserveRecent) || stmPreserveRecent < 0) {
        throw new Error(
          `backend.stm_preserve_recent_messages in ${configPath} must be an integer of 0 or more.`
        )
      }
      // Otherwise the summarizer raises "insufficient messages" on every turn
      if (useStmSummarization && stmPreserveRecent >= stmWindowSize) {
        throw new Error(
          `backend.stm_preserve_recent_messages in ${configPath} must be less than ` +
            `stm_window_size when use_stm_summarization is true.`
        )
      }
      // Checked before .trim(): a YAML number or list would crash there or reach the runtime
      if (typeof stmModelId !== "string") {
        throw new Error(`backend.stm_summarization_model_id in ${configPath} must be a string.`)
      }
      if (typeof stmPrompt !== "string") {
        throw new Error(`backend.stm_summarization_prompt in ${configPath} must be a string.`)
      }

      return {
        stack_name_base: stackNameBase,
        deploy_scope: deployScope,
        admin_user_email: parsedConfig.admin_user_email || null,
        backend: {
          pattern: parsedConfig.backend?.pattern || "ledgerlens",
          deployment_type: deploymentType,
          agent_name: parsedConfig.backend?.agent_name || "LedgerLensAgent",
          network_mode: networkMode,
          vpc: vpcConfig,
          use_long_term_memory: parsedConfig.backend?.use_long_term_memory === true,
          ltm_top_k: parsedConfig.backend?.ltm_top_k ?? 10,
          ltm_relevance_score: parsedConfig.backend?.ltm_relevance_score ?? 0.3,
          stm_window_size: stmWindowSize,
          use_stm_summarization: useStmSummarization,
          stm_summary_ratio: stmSummaryRatio,
          stm_preserve_recent_messages: stmPreserveRecent,
          stm_summarization_model_id: stmModelId.trim(),
          stm_summarization_prompt: stmPrompt.trim(),
          mcp_registry: {
            enabled: mcpRegistryEnabled,
            registry_id: mcpRegistryId,
          },
        },
        data: { as_of: asOf },
      }
    } catch (error) {
      throw new Error(`Failed to parse configuration file ${configPath}: ${error}`)
    }
  }

  public getProps(): AppConfig {
    return this.config
  }

  public get(key: string, defaultValue?: any): any {
    const keys = key.split(".")
    let value: any = this.config

    for (const k of keys) {
      if (typeof value === "object" && value !== null && k in value) {
        // nosemgrep: javascript.lang.security.audit.prototype-pollution.prototype-pollution-loop.prototype-pollution-loop — iterates over a trusted local YAML config object, not user-controlled input
        value = value[k]
      } else {
        return defaultValue
      }
    }

    return value
  }
}
