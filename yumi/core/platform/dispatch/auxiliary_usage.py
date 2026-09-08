"""Best-effort accounting for model work outside the streamed chat answer."""

from yumi.logging_config import get_logger

logger = get_logger(__name__)


def record_auxiliary_usage(
    *,
    kind: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
    estimated: bool = False,
    usage_parts: list[dict] | None = None,
) -> None:
    from yumi.core.features.config.paths import CONFIG_DIR
    from yumi.core.platform.plugins import get_current_identity, get_quota_policy
    from yumi.core.platform.runtime.assistant_context import conversation_session
    from yumi.core.platform.runtime.usage_context import usage_owner_id, usage_turn_id
    from yumi.core.platform.storage.sqlite_store import SQLiteStore

    if not (prompt_tokens or completion_tokens):
        return
    identity = get_current_identity()
    owner = usage_owner_id.get() or identity.user_id
    if kind == "tool_index":
        owner = "_system"
    try:
        SQLiteStore(CONFIG_DIR / "yumi.db").record_token_usage(
            session_id=conversation_session.get() if kind != "tool_index" else "",
            turn_id=usage_turn_id.get() if kind != "tool_index" else "",
            owner_user_id=owner,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usage_kind=kind,
            estimated=estimated,
            usage_parts=usage_parts
            if usage_parts is not None
            else (
                [
                    {
                        "model": model,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "cached_prompt_tokens": 0,
                    }
                ]
                if kind != "summary"
                else None
            ),
        )
    except Exception:
        logger.debug("Auxiliary usage persistence skipped", exc_info=True)
    try:
        if owner == identity.user_id and kind != "tool_index":
            quota = get_quota_policy()
            if kind == "summary":
                quota.record_chat_tokens(identity, prompt_tokens, completion_tokens, model=model)
            else:
                quota.record_embed_tokens(identity, prompt_tokens, model=model)
    except Exception:
        logger.debug("Auxiliary quota accounting skipped", exc_info=True)
