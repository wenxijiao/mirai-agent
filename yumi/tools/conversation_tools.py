"""Read saved tool data referenced by compact historical prompt excerpts."""

from __future__ import annotations

import json

from yumi.core.features.chat.context import get_chat_owner_user_id
from yumi.core.features.memory.history_payloads import saved_payload
from yumi.core.platform.plugins import SINGLE_USER_ID, get_current_identity, get_memory_factory, get_session_scope
from yumi.core.platform.storage.assistant_store import is_group_session


def read_conversation_record(event_id: str, offset: int = 0, limit: int = 4000) -> str:
    """Read one owner's saved tool result or tool attachment, in bounded pages."""
    owner = get_chat_owner_user_id()
    identity = get_current_identity()
    unavailable = json.dumps({"error": "Saved tool data is unavailable or was forgotten."})
    if identity.user_id not in (SINGLE_USER_ID, owner):
        return unavailable
    memory = get_memory_factory().get_for_session_owner(owner)
    row = memory.sqlite.get_message(str(event_id).strip())
    if (
        row is None
        or row.get("deleted_at") is not None
        or is_group_session(str(row.get("session_id") or ""))
        or get_session_scope().owner_user_from_session_id(str(row.get("session_id") or "")) != owner
        or not memory.can_recall(row)
    ):
        return unavailable
    session = memory.sqlite.get_session(row["session_id"])
    if session is None or session.get("status") == "deleted":
        return unavailable
    content = saved_payload(row)
    if content is None:
        return unavailable
    start = max(0, min(int(offset), len(content)))
    end = min(len(content), start + max(1, min(4000, int(limit))))
    while True:
        response = json.dumps(
            {
                "event_id": row["id"],
                "reference_only": True,
                "total_characters": len(content),
                "offset": start,
                "next_offset": end if end < len(content) else None,
                "content": content[start:end],
            },
            ensure_ascii=False,
        )
        if len(response) <= 7000 or end - start <= 1:
            return response
        end = start + max(1, (end - start) // 2)
