"""Request metadata follows async tool/model work without global user state."""

from contextvars import ContextVar
from dataclasses import dataclass, field

conversation_session: ContextVar[str] = ContextVar("assistant_session", default="")
source_channel: ContextVar[str | None] = ContextVar("assistant_source_channel", default=None)
message_media: ContextVar[dict | None] = ContextVar("assistant_message_media", default=None)
# A reset may interrupt active generation/confirmation. Executed side effects
# cannot be undone; all late persistence remains attached to the old segment.
active_requests: dict[str, set] = {}


def personal_store(owner: str):
    from yumi.core.platform.plugins import get_memory_factory
    from yumi.core.platform.storage.assistant_store import AssistantStore

    return AssistantStore(get_memory_factory().get_for_session_owner(owner).sqlite, owner)


@dataclass
class PromptSnapshot:
    """Immutable turn inputs plus completed tool spans; never a history window."""

    messages: list[dict] | None = None
    initial_note_ids: set[int] = field(default_factory=set)
    tool_messages: list[dict] = field(default_factory=list)
    redaction_stamp: str = ""
