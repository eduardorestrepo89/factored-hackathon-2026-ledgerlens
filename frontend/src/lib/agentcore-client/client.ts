// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { AgentCoreConfig, StreamCallback } from "./types"
import { createStrandsParser } from "./parsers/strands"
import { readSSEStream } from "./utils/sse"

export class AgentCoreClient {
  private runtimeArn: string
  private region: string

  constructor(config: AgentCoreConfig) {
    this.runtimeArn = config.runtimeArn
    this.region = config.region ?? "us-east-1"
  }

  generateSessionId(): string {
    return crypto.randomUUID()
  }

  async invoke(
    query: string,
    sessionId: string,
    accessToken: string,
    onEvent: StreamCallback
  ): Promise<void> {
    if (!accessToken) throw new Error("No valid access token found.")
    if (!this.runtimeArn) throw new Error("Agent Runtime ARN not configured.")

    const endpoint = `https://bedrock-agentcore.${this.region}.amazonaws.com`
    const escapedArn = encodeURIComponent(this.runtimeArn)
    const url = `${endpoint}/runtimes/${escapedArn}/invocations?qualifier=DEFAULT`

    const traceId = `1-${Math.floor(Date.now() / 1000).toString(16)}-${crypto.randomUUID()}`

    const body = {
      prompt: query,
      runtimeSessionId: sessionId,
    }

    // User identity is extracted server-side from the validated JWT token
    // (Authorization header), not sent in the payload body. This prevents
    // impersonation via prompt injection.
    const response = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Amzn-Trace-Id": traceId,
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(`HTTP ${response.status}: ${errorText}`)
    }

    await readSSEStream(response, createStrandsParser(), onEvent)
  }
}
