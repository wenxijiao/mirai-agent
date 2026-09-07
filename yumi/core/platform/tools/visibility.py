"""The model's tool policy, shared by routing, discovery and runtime context."""

from __future__ import annotations


def model_disabled_tools(identity, disabled: set[str], *, session_id: str | None = None) -> set[str]:
    from yumi.core.platform.plugins import get_session_scope
    from yumi.core.platform.runtime.assistant_context import conversation_session, personal_store
    from yumi.core.platform.storage.assistant_store import is_personal_session

    result = set(disabled)
    sid = session_id or conversation_session.get()
    if is_personal_session(sid):
        owner = get_session_scope().owner_user_from_session_id(sid)
        # Never use a model-supplied session to select someone else's policy.
        if identity.user_id not in (owner, "_local"):
            raise ValueError("Tool policy does not belong to this user")
        saved = personal_store(owner).get("tools", {})
        result.update(name for name, rule in saved.items() if rule.get("disabled") or rule.get("ai_access") == "none")
    return result
