import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export const qk = {
  health: ["health"] as const,
  sessions: ["sessions"] as const,
  messages: (id: string) => ["messages", id] as const,
  tools: ["tools"] as const,
  observability: ["observability"] as const,
  debugTurns: (sid?: string) => ["debug-turns", sid ?? "all"] as const,
  debugTurn: (id?: string | null) => ["debug-turn", id ?? "none"] as const,
  chatTurn: (id?: string | null) => ["chat-turn", id ?? "none"] as const,
  topology: ["topology"] as const,
  traces: (sid?: string) => ["traces", sid ?? "all"] as const,
  timers: ["timers"] as const,
  modelConfig: ["model-config"] as const,
  systemPrompt: ["system-prompt"] as const,
  sessionPrompt: (id: string) => ["session-prompt", id] as const,
}

export function useSessions() {
  return useQuery({ queryKey: qk.sessions, queryFn: () => api.listSessions("active") })
}

export function useTools() {
  return useQuery({ queryKey: qk.tools, queryFn: api.tools })
}

export function useObservability(refetchMs = 0) {
  return useQuery({
    queryKey: qk.observability,
    queryFn: () => api.observability(),
    refetchInterval: refetchMs || false,
  })
}

export function useDebugTurns(sessionId?: string, refetchMs = 0) {
  return useQuery({
    queryKey: qk.debugTurns(sessionId),
    queryFn: () => api.debugTurns(sessionId),
    refetchInterval: refetchMs || false,
  })
}

export function useDebugTurn(turnId?: string | null, refetchMs = 0) {
  return useQuery({
    queryKey: qk.debugTurn(turnId),
    queryFn: () => api.debugTurn(turnId as string),
    enabled: !!turnId,
    refetchInterval: refetchMs || false,
  })
}

export function useChatTurn(turnId?: string | null, enabled = true) {
  return useQuery({
    queryKey: qk.chatTurn(turnId),
    queryFn: () => api.chatTurn(turnId as string),
    enabled: enabled && !!turnId,
  })
}

export function useTopology(refetchMs = 0) {
  return useQuery({ queryKey: qk.topology, queryFn: api.topology, refetchInterval: refetchMs || false })
}

export function useTraces(sessionId?: string, refetchMs = 0) {
  return useQuery({
    queryKey: qk.traces(sessionId),
    queryFn: () => api.traces(sessionId),
    refetchInterval: refetchMs || false,
  })
}

export function useTimers(refetchMs = 0) {
  return useQuery({ queryKey: qk.timers, queryFn: api.timers, refetchInterval: refetchMs || false })
}

export function useModelConfig() {
  return useQuery({ queryKey: qk.modelConfig, queryFn: api.getModelConfig })
}

export function useSystemPrompt() {
  return useQuery({ queryKey: qk.systemPrompt, queryFn: api.getSystemPrompt })
}

export function useHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: api.health,
    refetchInterval: 15000,
    retry: false,
  })
}
