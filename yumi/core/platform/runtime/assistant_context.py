"""Request metadata follows async tool/model work without global user state."""

from contextvars import ContextVar

conversation_session: ContextVar[str] = ContextVar("assistant_session", default="")
source_channel: ContextVar[str | None] = ContextVar("assistant_source_channel", default=None)
# A reset may interrupt active generation/confirmation. Executed side effects
# cannot be undone; all late persistence remains attached to the old segment.
active_requests: dict[str, set] = {}


def personal_store(owner: str):
    from yumi.core.platform.plugins import get_memory_factory
    from yumi.core.platform.storage.assistant_store import AssistantStore

    return AssistantStore(get_memory_factory().get_for_session_owner(owner).sqlite, owner)
