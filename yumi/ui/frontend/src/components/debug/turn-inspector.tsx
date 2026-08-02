import { useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import {
  Activity,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Code2,
  Database,
  Download,
  Gauge,
  Layers3,
  LoaderCircle,
  MessageSquareText,
  Play,
  RefreshCw,
  Route,
  Sparkles,
  SquareTerminal,
  TriangleAlert,
  Wrench,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useDebugTurn, useDebugTurns } from "@/hooks/queries"
import { formatDuration, timeAgo, withCommas } from "@/lib/format"
import type {
  DebugLlmRound,
  DebugPromptMessage,
  DebugTimelineEvent,
  DebugTurn,
  DebugTurnSummary,
} from "@/lib/types"
import { cn } from "@/lib/utils"
import { useApp } from "@/store/app"

function jsonText(value: unknown): string {
  if (typeof value === "string") return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value ?? "")
  }
}

function statusVariant(status: string): "success" | "warning" | "destructive" | "muted" {
  if (status === "complete" || status === "success" || status === "stop") return "success"
  if (status === "running" || status === "waiting") return "warning"
  if (status === "error" || status === "blocked" || status === "length") return "destructive"
  return "muted"
}

function TurnRow({ turn, selected, onClick }: { turn: DebugTurnSummary; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group w-full border-b border-border px-4 py-3 text-left transition-colors last:border-b-0",
        selected ? "bg-primary/8" : "hover:bg-muted/45",
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "mt-1 flex size-7 shrink-0 items-center justify-center rounded-lg",
            turn.status === "running" ? "bg-warning/15 text-warning" : "bg-primary/10 text-primary",
          )}
        >
          {turn.status === "running" ? <LoaderCircle className="size-3.5 animate-spin" /> : <MessageSquareText className="size-3.5" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="min-w-0 flex-1 truncate text-sm font-medium">{turn.prompt_preview || "Untitled turn"}</p>
            <ChevronRight className={cn("size-3.5 shrink-0 text-muted-foreground transition", selected && "text-primary")} />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <span>{timeAgo(turn.started_at)}</span>
            <span>·</span>
            <span>{formatDuration(turn.duration_ms ?? 0)}</span>
            <span>·</span>
            <span>{turn.round_count} round{turn.round_count === 1 ? "" : "s"}</span>
            {turn.tool_call_count > 0 && (
              <>
                <span>·</span>
                <span>{turn.tool_call_count} tool{turn.tool_call_count === 1 ? "" : "s"}</span>
              </>
            )}
          </div>
          <div className="mt-2 flex items-center gap-1.5">
            <Badge variant={statusVariant(turn.status)} className="px-1.5 py-0 text-[10px]">
              {turn.status}
            </Badge>
            {turn.model && (
              <span className="max-w-[150px] truncate font-mono text-[10px] text-muted-foreground">{turn.model}</span>
            )}
            {turn.cache_hit_percent > 0 && (
              <span className="ml-auto text-[10px] font-medium text-success">{turn.cache_hit_percent}% cached</span>
            )}
          </div>
        </div>
      </div>
    </button>
  )
}

function Metric({ label, value, hint, icon: Icon }: { label: string; value: string; hint?: string; icon: typeof Clock3 }) {
  return (
    <div className="rounded-xl border border-border bg-card px-3.5 py-3">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
        <Icon className="size-3.5" />
        {label}
      </div>
      <div className="mt-1.5 text-lg font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

const TIMELINE_ICON: Record<string, typeof Play> = {
  turn: Play,
  routing: Route,
  llm_request: BrainCircuit,
  usage: Gauge,
  llm_finish: CheckCircle2,
  tool_calls: Wrench,
  tool_status: Activity,
  tool_result: SquareTerminal,
  confirmation: CircleDot,
  error: TriangleAlert,
}

function TimelineView({ events }: { events: DebugTimelineEvent[] }) {
  const visible = events.filter((e) => e.kind !== "usage")
  if (!visible.length) return <EmptyText>No timeline events recorded.</EmptyText>
  return (
    <div className="relative ml-1 space-y-0">
      <div className="absolute bottom-4 left-[15px] top-4 w-px bg-border" aria-hidden />
      {visible.map((event, index) => {
        const Icon = TIMELINE_ICON[event.kind] ?? CircleDot
        const bad = event.kind === "error" || event.status === "error"
        return (
          <div key={`${event.ts}-${index}`} className="relative flex gap-3 py-2.5">
            <div
              className={cn(
                "z-10 flex size-[31px] shrink-0 items-center justify-center rounded-full border bg-background",
                bad ? "border-destructive/40 text-destructive" : "border-border text-primary",
              )}
            >
              <Icon className="size-3.5" />
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{event.label}</span>
                {event.round != null && <Badge variant="muted">round {event.round}</Badge>}
                {event.status && <Badge variant={statusVariant(event.status)}>{event.status}</Badge>}
                {event.duration_ms != null && (
                  <span className="text-xs tabular-nums text-muted-foreground">{formatDuration(event.duration_ms)}</span>
                )}
              </div>
              {event.detail && <p className="mt-0.5 break-words text-xs text-muted-foreground">{event.detail}</p>}
              <p className="mt-1 text-[10px] text-muted-foreground/70">
                {new Date(event.ts).toLocaleTimeString()}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function RoundPicker({ rounds, value, onChange }: { rounds: DebugLlmRound[]; value: number; onChange: (v: number) => void }) {
  if (rounds.length <= 1) return null
  return (
    <div className="mb-4 flex flex-wrap gap-1.5">
      {rounds.map((round) => (
        <Button
          key={round.index}
          type="button"
          variant={round.index === value ? "secondary" : "outline"}
          size="sm"
          onClick={() => onChange(round.index)}
        >
          Round {round.index}
          {round.finish?.reason && <span className="ml-1 text-[10px] text-muted-foreground">{round.finish.reason}</span>}
        </Button>
      ))}
    </div>
  )
}

function roleTone(role: string): string {
  if (role === "system") return "border-primary/25 bg-primary/5"
  if (role === "user") return "border-blue-500/25 bg-blue-500/5"
  if (role === "assistant") return "border-success/25 bg-success/5"
  if (role === "tool") return "border-warning/25 bg-warning/5"
  return "border-border bg-muted/20"
}

function PromptMessageCard({ message }: { message: DebugPromptMessage }) {
  return (
    <details className={cn("group rounded-xl border", roleTone(message.role))} open={message.index === 0}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-3 marker:hidden">
        <Badge variant="outline" className="font-mono text-[10px]">
          {message.role}
        </Badge>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{message.label}</span>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          ≈ {withCommas(message.approx_tokens)} tokens
        </span>
        <ChevronRight className="size-4 text-muted-foreground transition-transform group-open:rotate-90" />
      </summary>
      <div className="border-t border-border/70 px-3.5 py-3">
        <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/85">
          {jsonText(message.content)}
        </pre>
        {message.tool_calls && (
          <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-background/70 p-3 font-mono text-xs">
            {JSON.stringify(message.tool_calls, null, 2)}
          </pre>
        )}
      </div>
    </details>
  )
}

function PromptView({ rounds }: { rounds: DebugLlmRound[] }) {
  const [roundIndex, setRoundIndex] = useState(rounds[0]?.index ?? 1)
  useEffect(() => setRoundIndex(rounds[0]?.index ?? 1), [rounds])
  const round = rounds.find((r) => r.index === roundIndex) ?? rounds[0]
  if (!round) return <EmptyText>No provider request was captured for this turn.</EmptyText>
  const approx = round.messages.reduce((sum, m) => sum + (m.approx_tokens || 0), 0)
  return (
    <div>
      <RoundPicker rounds={rounds} value={round.index} onChange={setRoundIndex} />
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{round.messages.length} messages</span>
        <span>·</span>
        <span>≈ {withCommas(approx)} display-estimated tokens</span>
        <span>·</span>
        <span>{round.tool_names.length} tools sent separately</span>
      </div>
      <div className="space-y-2">
        {round.messages.map((message) => (
          <PromptMessageCard key={`${round.index}-${message.index}`} message={message} />
        ))}
      </div>
      <p className="mt-3 text-[11px] text-muted-foreground">
        Per-message token counts are rough character-based estimates. Provider usage below is authoritative for the whole request.
      </p>
    </div>
  )
}

function toolFunction(tool: Record<string, unknown>): Record<string, unknown> {
  const fn = tool.function
  return fn && typeof fn === "object" ? (fn as Record<string, unknown>) : tool
}

function ToolsView({ turn }: { turn: DebugTurn }) {
  const [roundIndex, setRoundIndex] = useState(turn.rounds[0]?.index ?? 1)
  useEffect(() => setRoundIndex(turn.rounds[0]?.index ?? 1), [turn.id, turn.rounds])
  const round = turn.rounds.find((r) => r.index === roundIndex) ?? turn.rounds[0]
  if (!round) return <EmptyText>No tools were attached to a provider request.</EmptyText>
  return (
    <div>
      <RoundPicker rounds={turn.rounds} value={round.index} onChange={setRoundIndex} />

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Exposed tools ({round.tools.length})
          </h3>
          <div className="space-y-2">
            {round.tools.length === 0 && <EmptyText>No tools exposed.</EmptyText>}
            {round.tools.map((tool, index) => {
              const fn = toolFunction(tool)
              const name = String(fn.name ?? round.tool_names[index] ?? "unknown")
              return (
                <details key={`${name}-${index}`} className="group rounded-xl border border-border bg-card">
                  <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 marker:hidden">
                    <Wrench className="size-3.5 text-primary" />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs font-medium">{name}</span>
                    <ChevronRight className="size-4 text-muted-foreground transition-transform group-open:rotate-90" />
                  </summary>
                  <pre className="max-h-80 overflow-auto border-t border-border p-3 font-mono text-[11px] leading-relaxed">
                    {JSON.stringify(tool, null, 2)}
                  </pre>
                </details>
              )
            })}
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Model tool calls ({round.tool_calls.length})
            </h3>
            {round.tool_calls.length === 0 ? (
              <EmptyText>The model did not call a tool in this round.</EmptyText>
            ) : (
              <pre className="max-h-80 overflow-auto rounded-xl border border-border bg-muted/25 p-3 font-mono text-xs leading-relaxed">
                {JSON.stringify(round.tool_calls, null, 2)}
              </pre>
            )}
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Results ({round.tool_results.length})
            </h3>
            <div className="space-y-2">
              {round.tool_results.length === 0 && <EmptyText>No tool results in this round.</EmptyText>}
              {round.tool_results.map((result, index) => (
                <div key={index} className="rounded-xl border border-border bg-card p-3">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-xs font-medium">
                      {String(result.tool ?? result.resolved_tool ?? "tool")}
                    </span>
                    <Badge variant={statusVariant(String(result.status ?? ""))}>{String(result.status ?? "unknown")}</Badge>
                    <span className="text-[11px] tabular-nums text-muted-foreground">
                      {formatDuration(Number(result.duration_ms ?? 0))}
                    </span>
                  </div>
                  {result.result_preview != null && (
                    <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/35 p-2.5 font-mono text-[11px]">
                      {jsonText(result.result_preview)}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function num(value: unknown): number {
  const n = Number(value ?? 0)
  return Number.isFinite(n) ? n : 0
}

function UsageView({ turn }: { turn: DebugTurn }) {
  const usage = turn.usage ?? {}
  const prompt = num(usage.prompt_tokens)
  const completion = num(usage.completion_tokens)
  const cached = num(usage.cached_prompt_tokens)
  const percent = prompt ? Math.min(100, (cached / prompt) * 100) : 0
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Prompt" value={withCommas(prompt)} hint="input tokens" icon={MessageSquareText} />
        <Metric label="Completion" value={withCommas(completion)} hint="output tokens" icon={Sparkles} />
        <Metric label="Cached" value={withCommas(cached)} hint={`${percent.toFixed(1)}% of prompt`} icon={Database} />
        <Metric label="Duration" value={formatDuration(turn.duration_ms ?? 0)} hint={`${turn.rounds.length} LLM round(s)`} icon={Clock3} />
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">Prompt cache hit</span>
          <span className="tabular-nums text-muted-foreground">{percent.toFixed(1)}%</span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-success transition-all" style={{ width: `${percent}%` }} />
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          A zero value may mean no cache hit, a short prompt, or a provider that did not report cache usage.
        </p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Round</th>
              <th className="px-3 py-2 text-left font-medium">Provider / model</th>
              <th className="px-3 py-2 text-right font-medium">Prompt</th>
              <th className="px-3 py-2 text-right font-medium">Cached</th>
              <th className="px-3 py-2 text-right font-medium">Completion</th>
              <th className="px-3 py-2 text-right font-medium">Duration</th>
              <th className="px-3 py-2 text-left font-medium">Finish</th>
            </tr>
          </thead>
          <tbody>
            {turn.rounds.map((round) => (
              <tr key={round.index} className="border-t border-border">
                <td className="px-3 py-2 font-medium">{round.index}</td>
                <td className="max-w-[220px] px-3 py-2">
                  <div className="truncate">{round.provider}</div>
                  <div className="truncate font-mono text-[10px] text-muted-foreground">{round.model}</div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{withCommas(num(round.usage.prompt_tokens))}</td>
                <td className="px-3 py-2 text-right tabular-nums text-success">
                  {withCommas(num(round.usage.cached_prompt_tokens))}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{withCommas(num(round.usage.completion_tokens))}</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                  {formatDuration(round.duration_ms ?? 0)}
                </td>
                <td className="px-3 py-2">
                  <Badge variant={statusVariant(round.finish?.reason ?? "")}>{round.finish?.reason ?? "—"}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RawView({ turn }: { turn: DebugTurn }) {
  return (
    <pre className="max-h-[680px] overflow-auto rounded-xl border border-border bg-[hsl(228_18%_7%)] p-4 font-mono text-[11px] leading-relaxed text-slate-200">
      {JSON.stringify(turn, null, 2)}
    </pre>
  )
}

function EmptyText({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">{children}</div>
}

function downloadTurn(turn: DebugTurn) {
  const blob = new Blob([JSON.stringify(turn, null, 2)], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = `yumi-turn-${turn.id}.json`
  link.click()
  URL.revokeObjectURL(url)
}

export function TurnDetail({ turn }: { turn: DebugTurn }) {
  const usage = turn.usage ?? {}
  const prompt = num(usage.prompt_tokens)
  const cached = num(usage.cached_prompt_tokens)
  const cachePercent = prompt ? (cached / prompt) * 100 : 0
  const last = turn.rounds[turn.rounds.length - 1]

  return (
    <div className="min-w-0">
      <div className="border-b border-border px-5 py-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Badge variant={statusVariant(turn.status)}>{turn.status}</Badge>
              {turn.prompt_version && <Badge variant="outline">prompt v{turn.prompt_version}</Badge>}
              <span className="text-xs text-muted-foreground">{new Date(turn.started_at).toLocaleString()}</span>
            </div>
            <h3 className="mt-2 break-words text-base font-semibold leading-snug">{turn.prompt_preview || "Untitled turn"}</h3>
            <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground" title={turn.session_id}>
              {turn.session_id}
            </p>
          </div>
          {last && (
            <div className="flex items-start gap-2">
              <div className="text-right text-xs text-muted-foreground">
                <div>{last.provider}</div>
                <div className="mt-0.5 max-w-[220px] truncate font-mono">{last.model}</div>
              </div>
              <Button type="button" size="icon-sm" variant="outline" onClick={() => downloadTurn(turn)} title="Export turn JSON">
                <Download className="size-3.5" />
              </Button>
            </div>
          )}
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
          <Metric label="Duration" value={formatDuration(turn.duration_ms ?? 0)} icon={Clock3} />
          <Metric label="Prompt" value={withCommas(prompt)} hint={`${withCommas(num(usage.completion_tokens))} output`} icon={Layers3} />
          <Metric label="Cache" value={`${cachePercent.toFixed(1)}%`} hint={`${withCommas(cached)} tokens`} icon={Database} />
          <Metric
            label="Execution"
            value={`${turn.rounds.length} round${turn.rounds.length === 1 ? "" : "s"}`}
            hint={`${turn.summary.tool_call_count} tool call(s)`}
            icon={Activity}
          />
        </div>
      </div>

      <div className="p-5">
        <Tabs defaultValue="timeline">
          <TabsList className="h-auto max-w-full flex-wrap justify-start">
            <TabsTrigger value="timeline"><Route />Timeline</TabsTrigger>
            <TabsTrigger value="prompt"><MessageSquareText />Prompt</TabsTrigger>
            <TabsTrigger value="tools"><Wrench />Tools</TabsTrigger>
            <TabsTrigger value="usage"><Gauge />Usage</TabsTrigger>
            <TabsTrigger value="raw"><Code2 />Raw</TabsTrigger>
          </TabsList>
          <TabsContent value="timeline"><TimelineView events={turn.timeline} /></TabsContent>
          <TabsContent value="prompt"><PromptView rounds={turn.rounds} /></TabsContent>
          <TabsContent value="tools"><ToolsView turn={turn} /></TabsContent>
          <TabsContent value="usage"><UsageView turn={turn} /></TabsContent>
          <TabsContent value="raw"><RawView turn={turn} /></TabsContent>
        </Tabs>
      </div>
    </div>
  )
}

export function TurnInspector() {
  const activeSessionId = useApp((s) => s.activeSessionId)
  const [currentOnly, setCurrentOnly] = useState(Boolean(activeSessionId))
  const sessionFilter = currentOnly && activeSessionId ? activeSessionId : undefined
  const turnsQuery = useDebugTurns(sessionFilter, 3000)
  const turns = turnsQuery.data?.turns ?? []
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    if (!turns.length) {
      setSelectedId(null)
      return
    }
    if (!selectedId || !turns.some((turn) => turn.id === selectedId)) setSelectedId(turns[0].id)
  }, [turns, selectedId])

  const selectedSummary = useMemo(() => turns.find((turn) => turn.id === selectedId), [turns, selectedId])
  const detailQuery = useDebugTurn(selectedId, selectedSummary?.status === "running" ? 1500 : 0)

  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3.5">
        <div className="flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <BrainCircuit className="size-4.5" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">Turn Inspector</h2>
          <p className="text-xs text-muted-foreground">Follow each prompt, LLM round, tool call, and provider finish.</p>
        </div>
        <div className="flex items-center gap-2">
          {activeSessionId && (
            <Button
              type="button"
              size="sm"
              variant={currentOnly ? "secondary" : "outline"}
              onClick={() => setCurrentOnly((value) => !value)}
            >
              {currentOnly ? "Current chat" : "All chats"}
            </Button>
          )}
          <Button type="button" size="icon-sm" variant="outline" onClick={() => turnsQuery.refetch()} disabled={turnsQuery.isFetching}>
            <RefreshCw className={cn("size-3.5", turnsQuery.isFetching && "animate-spin")} />
          </Button>
        </div>
      </div>

      <div className="grid min-h-[540px] lg:grid-cols-[330px_minmax(0,1fr)]">
        <div className="max-h-[760px] overflow-y-auto border-b border-border bg-muted/15 lg:border-b-0 lg:border-r">
          {turnsQuery.isLoading && <div className="p-6 text-sm text-muted-foreground">Loading recent turns…</div>}
          {turnsQuery.isError && (
            <div className="p-6 text-sm text-destructive">Could not load recent turns: {String(turnsQuery.error)}</div>
          )}
          {!turnsQuery.isLoading && !turnsQuery.isError && turns.length === 0 && (
            <div className="flex min-h-[260px] flex-col items-center justify-center px-6 text-center">
              <Bot className="mb-3 size-8 text-muted-foreground/45" />
              <p className="text-sm font-medium">No turns captured yet</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Send a message in Chat, then return here. Turn details are saved automatically with conversation history.
              </p>
            </div>
          )}
          {turns.map((turn) => (
            <TurnRow key={turn.id} turn={turn} selected={turn.id === selectedId} onClick={() => setSelectedId(turn.id)} />
          ))}
        </div>

        <div className="min-w-0 bg-background/35">
          {detailQuery.isLoading && selectedId && (
            <div className="flex min-h-[420px] items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" /> Loading turn…
            </div>
          )}
          {detailQuery.isError && (
            <div className="p-6 text-sm text-destructive">Could not load this turn: {String(detailQuery.error)}</div>
          )}
          {detailQuery.data ? (
            <TurnDetail turn={detailQuery.data} />
          ) : (
            !detailQuery.isLoading && (
              <div className="flex min-h-[420px] flex-col items-center justify-center text-muted-foreground">
                <Layers3 className="mb-3 size-9 opacity-40" />
                <p className="text-sm">Select a turn to inspect it.</p>
              </div>
            )
          )}
        </div>
      </div>
      {turnsQuery.data?.retention?.message && (
        <div className="border-t border-border bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
          {turnsQuery.data.retention.message}
        </div>
      )}
    </section>
  )
}
