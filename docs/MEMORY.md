# Memory and chat context

This document describes what Mirai persists and how it reaches the model.

## Storage

- Chat messages (per `session_id`) are stored under the user memory directory (see `migrate_legacy_memory_dir()`), in **LanceDB** tables: `chat_history` and `chat_sessions`.
- `MiraiBot` keeps an in-memory LRU of at most **64** `Memory` instances; evicting one **does not delete** LanceDB rows. The next request for that session reloads from disk.

To delete persisted memory without wiping the rest of Mirai config, run:

```bash
mirai --cleanup-memory
```

This removes the current memory directory (`~/.mirai/memory/`) plus any legacy on-repo memory store if it still exists.

## What is persisted

| Data | Persisted |
|------|-----------|
| User messages | Yes |
| Final assistant **text** replies (no tool call in that step) | Yes |
| Assistant **tool_calls** + following **tool** results for each tool round | Yes (encoded rows; replayed in `get_context`) |
| Ephemeral-only context for the **current** multi-tool loop | Only the parts above are written; the in-memory `ephemeral_messages` list itself is not stored as a blob |

## Retrieval (`Memory.get_context`)

1. One **system** message: global or per-session prompt (`get_system_prompt` / `get_session_prompt`).
2. Optional **cross-session** block (`memory_max_related_messages` > 0): substring or vector search; if the query embedding is **degenerate** (e.g. all zeros), search falls back to **substring** match to avoid meaningless ANN results.
3. Recent in-session rows (up to `memory_max_recent_messages`), including replayed **assistant+tool_calls** and **tool** rows when present.

## Chat request extras (system message)

Configurable in `~/.mirai/config.json` or via `GET`/`PUT /config/model`:

- `chat_append_current_time` — append `[Current Time] ...` to system (default: `true`).
- `chat_append_tool_use_instruction` — append the English tool-use policy when tools are enabled (default: `true`).

Environment overrides (optional): `MIRAI_CHAT_APPEND_CURRENT_TIME`, `MIRAI_CHAT_APPEND_TOOL_INSTRUCTION` — set to `0`, `false`, or `no` to disable.
