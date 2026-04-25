"""Prompt context assembly for Mirai memory."""

from __future__ import annotations

import json
from typing import Any

from mirai.core.config import load_model_config
from mirai.core.memories.constants import MIRAI_V1_TOOL_CALLS, MIRAI_V1_TOOL_RESULT
from mirai.core.memories.retrieval import HybridRetriever
from mirai.core.memories.transcript import trim_leading_orphan_tool_rows, trim_trailing_incomplete_tool_rows


class ContextBuilder:
    """Build OpenAI-style messages from memory layers."""

    def __init__(self, memory: Any):
        self.memory = memory
        self.retriever = HybridRetriever(memory)

    def build(self, query: str | None = None, max_cross_session: int | None = None) -> list[dict]:
        cfg = load_model_config()
        max_recent = max(1, min(500, int(cfg.memory_max_recent_messages)))
        if max_cross_session is None:
            max_cross = max(0, min(100, int(cfg.memory_max_related_messages)))
        else:
            max_cross = max(0, min(100, int(max_cross_session)))

        formatted_messages = [self.memory.get_system_message()]
        if query:
            structured = self._structured_memory_message(query, limit=max_cross)
            if structured:
                formatted_messages.append(structured)

            summary = self._session_summary_message()
            if summary:
                formatted_messages.append(summary)
        elif self._session_summary_message():
            formatted_messages.append(self._session_summary_message())

        if query and max_cross > 0:
            related = self.memory.build_related_memory_message(
                query, exclude_session_id=self.memory.session_id, limit=max_cross
            )
            if related:
                formatted_messages.append(related)

        formatted_messages.extend(self._recent_transcript(max_recent))
        return formatted_messages

    def _session_summary_message(self) -> dict | None:
        row = self.memory.get_session_summary(self.memory.session_id)
        if not row:
            return None
        summary = str(row.get("summary") or "").strip()
        if not summary:
            return None
        return {
            "role": "system",
            "content": f"Current session summary:\n{summary}",
        }

    def _structured_memory_message(self, query: str, *, limit: int) -> dict | None:
        if limit <= 0:
            return None
        candidates = self.retriever.structured(query, limit=min(12, max(4, limit)))
        if not candidates:
            return None
        lines = ["Structured memory likely relevant to this request:"]
        for c in candidates:
            prefix = c.kind.replace("_", " ")
            source = f"{c.source}:{c.session_id}" if c.session_id else c.source
            lines.append(f"- [{prefix}; {source}; score={c.score:.2f}] {c.content[:500]}")
        return {"role": "system", "content": "\n".join(lines)}

    def _recent_transcript(self, max_recent: int) -> list[dict]:
        if not self.memory._table_exists():
            return []

        table = self.memory._open_table()
        where_clause = self.memory._build_where_clause("session_id", self.memory.session_id)
        total_messages = table.count_rows(where_clause)
        offset = max(total_messages - max_recent, 0)
        limit = max_recent

        base = table.search(query=None, ordering_field_name="timestamp_num").where(where_clause)

        def _fetch_window() -> list[dict]:
            return base.offset(offset).limit(limit).to_list()

        results = _fetch_window()
        guard = 0
        while results and results[0].get("role") == "tool" and offset > 0 and guard < 48:
            step = min(64, offset)
            offset -= step
            limit += step
            results = _fetch_window()
            guard += 1

        results = trim_leading_orphan_tool_rows(results)
        results = trim_trailing_incomplete_tool_rows(results)
        return [_format_transcript_message(msg) for msg in results]


def _format_transcript_message(msg: dict) -> dict:
    raw = msg.get("content") or ""
    if msg["role"] == "assistant":
        if raw.startswith(MIRAI_V1_TOOL_CALLS):
            try:
                data = json.loads(raw[len(MIRAI_V1_TOOL_CALLS) :])
                tcalls = data.get("tool_calls")
                if isinstance(tcalls, list) and tcalls:
                    return {
                        "role": "assistant",
                        "content": data.get("content", ""),
                        "tool_calls": tcalls,
                    }
            except (json.JSONDecodeError, TypeError):
                pass
        return {"role": "assistant", "content": raw}
    if msg["role"] == "user":
        return {"role": "user", "content": f"[{msg['timestamp']}] {raw}"}
    if msg["role"] == "tool":
        if raw.startswith(MIRAI_V1_TOOL_RESULT):
            try:
                data = json.loads(raw[len(MIRAI_V1_TOOL_RESULT) :])
                return {"role": "tool", "name": data.get("name") or "tool", "content": str(data.get("content", ""))}
            except (json.JSONDecodeError, TypeError):
                return {"role": "tool", "name": "tool", "content": raw}
        return {"role": "tool", "name": "tool", "content": raw}
    return {"role": msg["role"], "content": raw}
