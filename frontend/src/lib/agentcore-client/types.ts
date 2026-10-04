// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/** Configuration for AgentCoreClient */
export interface AgentCoreConfig {
  runtimeArn: string
  region?: string
}

/** Stream event types emitted by parsers */
export type StreamEvent =
  | { type: "text"; content: string }
  | { type: "tool_use_start"; toolUseId: string; name: string }
  | { type: "tool_use_delta"; toolUseId: string; input: string }
  | { type: "tool_result"; toolUseId: string; result: string }
  | { type: "message"; role: string; content: unknown[] }
  | { type: "result"; stopReason: string }
  | { type: "lifecycle"; event: string }
  // A claim or hand-off paused for the customer's Yes/No (agent tools/confirmation_hook.py)
  | { type: "confirmation"; id: string; tool: string; toolUseId: string; details: Record<string, unknown> }

/** Callback invoked with each stream event */
export type StreamCallback = (event: StreamEvent) => void

/** Parses a single SSE line and emits events via callback */
export type ChunkParser = (line: string, callback: StreamCallback) => void
