"""Built-in tools for user-controlled stable context."""

from __future__ import annotations

from yumi.core.features.chat.context import get_chat_owner_user_id
from yumi.core.features.memory.models import LONG_TERM_MEMORY_KINDS
from yumi.core.platform.plugins import get_memory_factory

_STABLE_USER_CONTEXT_SESSION = "__stable_user_context__"
_DISALLOWED_KINDS = {"tool_observation"}
_DEFAULT_KIND = "fact"


def _memory_store():
    return get_memory_factory().get_for_session_owner(get_chat_owner_user_id())


def _normalize_kind(kind: str | None) -> str:
    normalized = str(kind or _DEFAULT_KIND).strip().lower().replace(" ", "_")
    if normalized not in LONG_TERM_MEMORY_KINDS or normalized in _DISALLOWED_KINDS:
        allowed = ", ".join(sorted(k for k in LONG_TERM_MEMORY_KINDS if k not in _DISALLOWED_KINDS))
        raise ValueError(f"kind must be one of: {allowed}.")
    return normalized


def remember_user_context(content: str, kind: str = _DEFAULT_KIND, importance: float = 0.85) -> str:
    """Save a durable user context memory.

    Use this only when the user explicitly asks Yumi to remember something, or
    when the user directly confirms that a suggested memory should be saved.
    Do not save secrets, passwords, payment details, or sensitive personal data
    unless the user clearly asks for that exact information to be remembered.
    """
    normalized_content = " ".join(str(content or "").split())
    if not normalized_content:
        raise ValueError("content cannot be empty.")
    from yumi.core.features.assistant.personalization import explicit_language

    if language := explicit_language(normalized_content):
        return set_response_language(language)
    normalized_kind = _normalize_kind(kind)
    score = max(0.0, min(1.0, float(importance)))
    from yumi.core.platform.runtime.assistant_context import conversation_session

    memory = _memory_store()
    source_ids = []
    if conversation_session.get():
        recent = memory.sqlite.recent_transcript_rows(conversation_session.get(), 30)
        users = [r for r in recent if r.get("role") == "user"]
        if users:
            source_ids = [users[-1]["id"]]
    from yumi.core.features.assistant.personalization import BEHAVIOR_KINDS, save_rule
    from yumi.core.platform.storage.assistant_store import AssistantStore

    if normalized_kind in BEHAVIOR_KINDS:
        row = save_rule(AssistantStore(memory.sqlite, get_chat_owner_user_id()), normalized_content,
                        kind=normalized_kind, source_ids=source_ids)["memory"]
        return f"Remembered {row['kind']} memory {row['id']}: {row['content']}"
    row = memory.create_long_term_memory(
        kind=normalized_kind,
        content=normalized_content,
        session_id=_STABLE_USER_CONTEXT_SESSION,
        source_message_ids=source_ids,
        confidence=0.95,
        importance=score,
    )
    return f"Remembered {row['kind']} memory {row['id']}: {row['content']}"


def set_response_language(language: str) -> str:
    """Save the user's explicitly requested default reply language. Use auto to follow each message's language."""
    from yumi.core.features.assistant.personalization import save_preferences
    from yumi.core.platform.storage.assistant_store import AssistantStore

    saved = save_preferences(AssistantStore(_memory_store().sqlite, get_chat_owner_user_id()), response_language=language)
    return f"Saved response language: {saved['response_language']}. This updates the same preference as Personalization."


def list_user_context(kind: str = "", limit: int = 20) -> str:
    """List durable stable user context memories Yumi currently has saved."""
    normalized_kind = _normalize_kind(kind) if str(kind or "").strip() else None
    capped = max(1, min(50, int(limit)))
    from yumi.core.features.assistant.personalization import BEHAVIOR_KINDS, explicit_language, preferences
    from yumi.core.platform.storage.assistant_store import AssistantStore

    memory = _memory_store()
    values = preferences(AssistantStore(memory.sqlite, get_chat_owner_user_id()))
    rows = memory.list_long_term_memories(kind=normalized_kind, session_id=_STABLE_USER_CONTEXT_SESSION, limit=10000)
    rows = [row for row in rows if row.get("kind") not in _DISALLOWED_KINDS
            and not (row["kind"] in BEHAVIOR_KINDS and explicit_language(row["content"]))
            and memory.can_recall(row)][:capped]
    lines = [f"Response language: {values['response_language']} (use set_response_language to change; auto to reset).",
             "Stable user context memories:"]
    if not rows:
        lines.append("No stable user context memories are saved.")
    for row in rows:
        lines.append(f"- {row['id']} [{row['kind']}] {row['content']}")
    return "\n".join(lines)


def update_user_context(memory_id: str, content: str) -> str:
    """Replace an existing saved preference after the user asks to change it."""
    from yumi.core.features.assistant.personalization import BEHAVIOR_KINDS, preferences, save_rule
    from yumi.core.platform.storage.assistant_store import AssistantStore

    memory = _memory_store()
    store = AssistantStore(memory.sqlite, get_chat_owner_user_id())
    preferences(store)
    existing = next((r for r in store.memories() if r["id"] == memory_id
                     and r["kind"] in BEHAVIOR_KINDS and r["session_id"] == _STABLE_USER_CONTEXT_SESSION), None)
    if existing is None:
        raise ValueError("Saved preference not found. Use list_user_context to find its current id.")
    source_ids = []
    from yumi.core.platform.runtime.assistant_context import conversation_session
    if conversation_session.get():
        users = [r for r in memory.sqlite.recent_transcript_rows(conversation_session.get(), 30)
                 if r.get("role") == "user"]
        if users:
            source_ids = [users[-1]["id"]]
    result = save_rule(store, content, memory_id=memory_id, kind=existing["kind"], source_ids=source_ids)
    if result.get("saved_as") == "response_language":
        return f"Saved response language: {result['preference']['response_language']}. Replaced the previous rule."
    row = result["memory"]
    return f"Updated {row['kind']} memory {row['id']}: {row['content']}"


def forget_user_context(memory_id: str) -> str:
    """Delete a durable user context memory by id.

    Use after the user asks Yumi to forget a saved memory. If the user names a
    memory but not its id, call list_user_context first to find the matching id.
    """
    normalized_id = str(memory_id or "").strip()
    if not normalized_id:
        raise ValueError("memory_id cannot be empty.")
    deleted = _memory_store().delete_long_term_memory(normalized_id)
    if not deleted:
        return f"No stable user context memory found for id {normalized_id}."
    return f"Forgot stable user context memory {normalized_id}."
