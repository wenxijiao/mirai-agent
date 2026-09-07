# Agent turn context and tool discovery

Each request retains an in-memory snapshot of its initial prompt, recalled facts,
related history and runtime notes. Completed tool spans are appended to that
snapshot and independently persisted. Reading the next model round does not
reconstruct the active task from the sliding history window. A memory redaction
invalidates an in-flight snapshot.

Tool results retain their call IDs through approval, execution, SQLite and replay.
Current turns reject missing, duplicate and unmatched IDs. Legacy results can be
recovered by a unique function name; ambiguous outcomes are explicitly unknown.
No positional pairing is performed.

## Tool visibility and discovery

Routing, discovery, forced additions and connected-device context share the scoped
catalog, including personal `disabled` and `ai_access=none` settings. Execution
rechecks policy after confirmation. Manual execution keeps its separate policy.

`YUMI_EDGE_TOOLS_ROUTING_MODE=on_demand` exposes a small core set initially and
avoids semantic tool search for ordinary chat. `discover_app_tools` searches core
and edge functions and admits at most six relevant functions, never all siblings
of a matching device. Prior sticky/per-turn/off modes remain supported; the OSS
model default stays sticky for compatibility. Nexus enables on-demand mode.

Tool metadata vectors are cached across restarts by provider endpoint, model and
content hash. Edge registration starts bounded background warm-up when embedding
is configured. Only metadata vectors are persisted, never request text or query
vectors. Missing indexes are filled lazily on discovery. Keyword ranking is the
fallback if semantic retrieval is unavailable.

## Budgets and termination

Model configuration:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `chat_input_token_budget` | 32,000 | Estimated messages plus function schemas |
| `chat_max_output_tokens` | 4,096 | Provider generation limit |
| `tool_schema_token_budget` | 6,000 | Function schemas; latest discoveries take priority |

Input estimates are conservative, not a model-specific tokenizer. The input and
output limits must be configured within the chosen model's context capacity.
Old completed turns are removed as units before shortening oversized tool results.
The active user task, tool pair identities and required rules/recall remain. If
those still exceed the budget, the request fails clearly before model execution.

After ten tool rounds the model receives one no-tools closing round. A tool
timeout is recorded as an unknown outcome, because local threads and remote
operations may still complete. The turn closes without automatically retrying.
This is not a claim of transactional exactly-once execution across edge systems.

## Reasoning and accounting

DeepSeek receives an explicit thinking enabled/disabled setting. Thinking tool
requests replay available historical reasoning, including final assistant turns;
legacy messages have an empty reasoning field. Other providers retain their own
capabilities. Traces separate the requested adapter setting from observed reasoning
and include per-message and schema input estimates.

The usage ledger has additive `usage_kind` and `estimated` columns. Chat, summary,
embedding and tool search consumption is associated with the account and originating
turn when available. Tool metadata indexing is system-owned. API-reported embedding
usage is preferred; estimates are marked. Monthly totals include auxiliary work,
while request counts count chat turns. Earlier usage is not retroactively inferred.
