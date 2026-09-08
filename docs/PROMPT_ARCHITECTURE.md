# Prompt Architecture

Yumi builds each model turn as layered context, then provider adapters map the
internal OpenAI-style message list to OpenAI-compatible, Claude, Gemini, or
other provider wire formats.

## Layers

1. **Base identity**
   - Yumi's persona, tone, language behavior, honesty rules, and context rules.
   - Stored in `DEFAULT_SYSTEM_PROMPT`, plus plugin sections and user addenda.

2. **Stable User Context**
   - Durable long-term memories such as profile, preferences, routines, projects,
     relationships, constraints, communication style, and `do_not_assume`.
   - Injected as its own system message every turn when saved memories exist.
   - Managed through built-in tools: `remember_user_context`,
     `list_user_context`, and `forget_user_context`.
   - IDs already included in this layer are excluded from query-driven fact
     retrieval. Personalization behavior rules remain in their separate fixed
     rules block. Retrieval can still include facts outside the stable-layer cap.
   - The system block states the category distinction briefly. Detailed examples
     and category instructions live in the memory tool schema instead of being
     duplicated verbatim in both places.

3. **Turn Runtime Context**
   - Fresh, turn-only context collected before generation.
   - Includes connected edge summaries and autorun context results grouped by
     local tools and by edge.
   - Produced by `mode="autorun"` tools (legacy wire flag:
     `proactive_context`) and never persisted to chat history.

4. **Conversation history**
   - Recent user/assistant/tool transcript plus query-relevant structured memory.
   - The recent transcript is the current session plus sibling sessions for the
     same owner (`voice_`, `tg_`, `dc_`, `line_`, `chat_`), with sibling turns
     labeled by channel. It is not an unbounded dump of every conversation.
   - The latest user turn stays verbatim. Older tool results and manual tool
     attachments over 1,800 characters become bounded head/tail excerpts in the
     prompt only. Original records in chat/history remain unchanged. Excerpts
     carry an event ID for the discoverable `read_conversation_record` tool,
     which reads exact saved data in pages and enforces ownership and forgetting.
     Ordinary text, call IDs and current-turn tool execution are preserved.

5. **Current user input**
   - The user's message for this turn. Runtime context is never mixed into the
     user's message body.
   - Added as the final user message, separate from the stored recent transcript.

6. **Callable tools**
   - Passed through the provider's tool/function API. Pinned tools are exposed
     every turn outside the dynamic retrieval cap; dynamic tools are selected by
     routing; autorun tools are not exposed as callable tools for that turn.

7. **Tool results**
   - Added only after the model requests a tool call and the runtime executes it.
   - A request snapshot preserves the original task and its complete active tool
     sequence across iterations; the old-history excerpts are never applied to
     the snapshot's in-flight tool results.

## Embedding work

Each chat request owns a bounded in-memory vector cache. Repeated text for the
same owner, provider instance and model shares one embedding request, including
concurrent worker-thread callers. Only actual provider calls record usage. Cache
keys contain text hashes, not prompt text; vectors are copied on return. Failed
or degenerate results are not reused. Closing the turn clears and disables the
cache, including copies inherited by background tasks. Standalone indexing does
not inherit a process-wide cache of user content.

Tool-discovery query vectors use that same request cache. Only static tool and
device descriptions enter the shared bounded process/disk cache. Request text
does not enter it. Description keys include provider endpoint, model and a hash
of the description; changing a description or model naturally invalidates it.

## Cache identity and usage

DeepSeek requests carry an opaque SHA-256 account identifier in `extra_body.user_id`.
It is stable across channels, context resets and requests, but differs by owner.
No email address, raw account identifier, session or request ID is transmitted as
the cache identity. The provider's account-isolation control is separate from
Yumi's own conversation and tool authorization.

Each usage ledger row can retain the observed per-call input, output, cache read,
cache write and price snapshot in `usage_details_json` (SQLite schema version 4).
Zero cache hits and absent cache telemetry are different. Older/unreported input
remains an unknown category, excluded from the hit-rate denominator; coverage
is reported separately. Cache reads are a subset of input, never added twice.
Chat-loop and summary usage preserve provider metadata through persistence.

Monthly, daily and paginated request APIs expose the same cache partitions and
price coverage. Price estimates use integer nano-USD and the public rates
verified on 2026-09-08, captured at request time. Current supported rates are the
three official DeepSeek v4 model names, including weekday UTC peak/off-peak
periods. Compatible proxy URLs and other providers remain unpriced. Missing
cache telemetry can price only the known output portion. Historical rows are
not assigned today's prices, and changing the rate table never reprices stored
snapshots. Estimates exclude voice, external tools, credits, taxes and discounts.

Sources: [DeepSeek prices](https://api-docs.deepseek.com/quick_start/pricing/)
and [account isolation](https://api-docs.deepseek.com/quick_start/rate_limit/).

## Provider Mapping

- OpenAI-compatible providers receive system messages, user/assistant history,
  and `role="tool"` results.
- DeepSeek thinking requests that include tools retain prior `reasoning_content`
  as required by its API. Other supported modes can strip historical reasoning.
  Payload excerpts do not remove reasoning fields required for provider replay.
- Claude receives combined system text as a top-level system parameter; tool
  calls/results are converted to `tool_use` / `tool_result` content blocks.
- Gemini receives combined system text as `system_instruction`; assistant turns
  map to `model`, and tool results map to function response parts.

Keep new prompt behavior in Yumi's internal layers first. Provider adapters
should only translate that structure to a provider-specific payload.
