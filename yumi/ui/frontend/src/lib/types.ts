// Types mirroring the Yumi core HTTP API (see docs/HTTP_API.md).

export type Role = "user" | "assistant" | "system" | "tool"

export interface ChatMessage {
  id: string
  turn_id?: string
  role: Role
  content: string
  thought?: string
}

export interface Session {
  session_id: string
  title: string
  status: string
  is_pinned: boolean
  message_count: number
  created_at?: string
  updated_at?: string
  last_message_at?: string
}

// One line of the POST /chat NDJSON stream.
export type ChatEvent =
  | { type: "text"; content: string }
  | { type: "thought"; content: string }
  | { type: "tool_status"; status: "running" | "success" | "error" | "denied"; content: string }
  | {
      type: "tool_confirmation"
      call_id: string
      tool_name: string
      full_tool_name?: string
      arguments: Record<string, unknown>
    }
  | { type: "error"; content: string; code?: string }

export type ToolDecision = "allow" | "deny" | "always_allow"

export interface ServerTool {
  name: string
  description: string
  disabled: boolean
  require_confirmation: boolean
}

export interface EdgeTool {
  name: string
  full_name: string
  description: string
  disabled: boolean
  require_confirmation: boolean
}

export interface EdgeDevice {
  edge_name: string
  online: boolean
  tools: EdgeTool[]
}

export interface ToolsResponse {
  server_tools: ServerTool[]
  edge_devices: EdgeDevice[]
  disabled_tools: string[]
  confirmation_tools: string[]
  always_allowed_tools: string[]
}

export interface Trace {
  id?: string
  ts: string
  session_id: string
  tool_name: string
  display_name?: string
  kind?: string
  edge_name?: string | null
  status: string
  duration_ms: number
  arguments?: unknown
  result_preview?: string
}

export interface TopologyEdge {
  edge_name: string
  online: boolean
  tool_count: number
}

export interface Topology {
  server: { id: string; label: string; role: string }
  local_tool_count: number
  edges: TopologyEdge[]
}

export interface Timer {
  timer_id: string
  description: string
  session_id?: string
  owner_id?: string
  fire_at?: string
  [k: string]: unknown
}

export interface ModelConfig {
  chat_provider: string
  chat_model: string
  embedding_provider: string
  embedding_model: string
  memory_max_recent_messages: number
  memory_max_related_messages: number
  chat_append_current_time?: boolean
  chat_append_tool_use_instruction?: boolean
  edge_tools_enable_dynamic_routing?: boolean
  edge_tools_retrieval_limit?: number
  stt_provider?: string
  stt_backend?: string
  stt_model?: string
  stt_language?: string
  tts_provider?: string
  tts_voice?: string
  tts_model?: string
  tts_language?: string
  openai_api_key_saved?: boolean
  gemini_api_key_saved?: boolean
  claude_api_key_saved?: boolean
  deepseek_api_key_saved?: boolean
  grok_api_key_saved?: boolean
  tts_api_key_saved?: boolean
  openai_base_url?: string
  deepseek_base_url?: string
  grok_base_url?: string
  [k: string]: unknown
}

export interface SystemPrompt {
  system_prompt: string
  is_default: boolean
}

export interface SessionPrompt {
  session_id: string
  system_prompt: string
  is_custom: boolean
}

export interface SearchResult {
  id: string
  session_id: string
  role: Role
  content: string
  thought?: string
  timestamp?: string
  score?: number
  [k: string]: unknown
}

// ── /debug/observability payload ──

export interface ObservabilityEdgeTool {
  name: string
  full_name: string
  always_include: boolean
  require_confirmation: boolean
}

export interface ObservabilityEdge {
  connection_key: string
  edge_name: string
  owner_user_id: string | null
  online: boolean
  tool_count: number
  tools: ObservabilityEdgeTool[]
}

export interface RoutingTrace {
  id?: string
  ts: string
  session_id: string
  query_preview?: string
  core_count?: number
  total_edge_count?: number
  selected_edge_count?: number
  selected_edge_tools?: string[]
  dynamic_routing_enabled?: boolean
  elapsed_ms?: number
}

export interface ObservabilityDiagnosis {
  level: "ok" | "warning" | "info"
  message: string
}

export interface Observability {
  identity: { user_id: string | null }
  config: {
    dynamic_routing_enabled?: boolean
    edge_tools_retrieval_limit?: number
    edge_tools_always_expose_below?: number
    embedding_model_set?: boolean
  }
  edges: ObservabilityEdge[]
  routing_traces: RoutingTrace[]
  tool_calls: Trace[]
  diagnosis: ObservabilityDiagnosis[]
}

// ── /debug/turns payload ──

export interface DebugTurnSummary {
  trace_schema_version?: number
  id: string
  session_id: string
  owner_user_id?: string
  prompt_preview: string
  started_at: string
  ended_at?: string | null
  duration_ms?: number | null
  status: "running" | "complete" | "error" | "interrupted" | string
  provider: string
  model: string
  round_count: number
  tool_call_count: number
  prompt_tokens: number
  completion_tokens: number
  cached_prompt_tokens: number
  cache_hit_percent: number
  finish_reason?: string | null
  response_preview?: string
  prompt_version?: string
  prompt_catalog_hash?: string
}

export interface DebugTimelineEvent {
  ts: string
  kind: string
  label: string
  round?: number | null
  status?: string | null
  detail?: string | null
  duration_ms?: number | null
  tools?: string[]
  [k: string]: unknown
}

export interface DebugPromptMessage {
  index: number
  role: string
  label: string
  content: unknown
  content_chars: number
  approx_tokens: number
  name?: string
  tool_call_id?: string
  tool_calls?: unknown[]
  reasoning_content?: unknown
}

export interface DebugLlmRound {
  index: number
  started_at: string
  ended_at?: string | null
  duration_ms?: number | null
  provider: string
  model: string
  messages: DebugPromptMessage[]
  tools: Record<string, unknown>[]
  tool_names: string[]
  usage: Record<string, unknown>
  finish?: { reason?: string; provider_reason?: string | null; [k: string]: unknown } | null
  tool_calls: Record<string, unknown>[]
  tool_results: Record<string, unknown>[]
  response_text: string
  reasoning_text: string
  note?: string | null
}

export interface DebugTurn {
  trace_schema_version?: number
  id: string
  session_id: string
  prompt: string
  prompt_preview: string
  think: boolean
  timer_callback: boolean
  started_at: string
  ended_at?: string | null
  duration_ms?: number | null
  status: string
  prompt_version?: string
  prompt_catalog_hash?: string
  routing: Record<string, unknown>
  rounds: DebugLlmRound[]
  timeline: DebugTimelineEvent[]
  usage?: Record<string, unknown>
  tool_loop_events?: Record<string, unknown>[]
  summary: DebugTurnSummary
}
