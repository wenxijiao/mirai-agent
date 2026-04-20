"""Shared mutable state and helpers for the Mirai core API.

All module-level collections that used to live at the top of ``api.py``
are gathered here so that sub-modules (edge handling, timer management)
can import them without circular dependencies.

Per-user / multi-tenant scoping (memory store, edge connection key,
tool schema filtering) is delegated to the plugin layer so the OSS core
stays in single-user mode by default.
"""

import asyncio

from mirai.core.memories.memory import Memory
from mirai.logging_config import get_logger

logger = get_logger(__name__)

# Set True after SIGTERM so load balancers stop routing new traffic (see routes lifespan).
server_draining: bool = False

# ── bot singleton ──

bot = None  # set by lifespan; typed as MiraiBot | None

# ── edge connections ──

ACTIVE_CONNECTIONS: dict = {}
EDGE_TOOLS_REGISTRY: dict = {}
PENDING_TOOL_CALLS: dict = {}
PENDING_EDGE_OPS: dict = {}
RELAY_EDGE_PEERS: dict = {}

# ── tool policy ──

DISABLED_TOOLS: set[str] = set()
CONFIRMATION_TOOLS: set[str] = set()
ALWAYS_ALLOWED_TOOLS: set[str] = set()
PENDING_CONFIRMATIONS: dict[str, asyncio.Future] = {}

# ── sessions ──

SESSION_LOCKS: dict[str, asyncio.Lock] = {}

# ── timers ──

TIMER_TASKS: dict[str, asyncio.Task] = {}
# (queue, subscriber_user_id): ``None`` = receive all timers (single-user / compat); else filter by owner.
TIMER_SUBSCRIBERS: list[tuple[asyncio.Queue, str | None]] = []

# ── relay (enterprise plugin attaches a RelayClient here; OSS leaves it None) ──

RELAY_CLIENT = None

# ── constants ──

TOOL_CALL_TIMEOUT_DEFAULT = 30
MAX_TOOL_LOOPS = 10
# Retries when the model emits tool_calls that cannot be normalized / executed.
MAX_TOOL_CALL_FORMAT_RETRIES = 3
LOCAL_TOOL_TIMEOUT_DEFAULT = 30


# ── bot accessor ──


def get_bot():
    """Return the active MiraiBot instance or raise RuntimeError."""
    if bot is None:
        raise RuntimeError(
            "Mirai server has no configured chat model. Run `mirai --setup` or start with `mirai --server`."
        )
    return bot


# ── memory store ──

_memory_store: Memory | None = None


def get_memory_store() -> Memory:
    global _memory_store
    if _memory_store is None:
        _memory_store = Memory(session_id="default")
    return _memory_store


def get_memory_store_for_identity(identity) -> Memory:
    """Return the Memory store for *identity* via the plugin layer."""
    from mirai.core.plugins import get_memory_factory

    return get_memory_factory().get_for_identity(identity)


# ── session lock ──


def get_session_lock(session_id: str) -> asyncio.Lock:
    lock = SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        SESSION_LOCKS[session_id] = lock
    return lock


def prune_session_locks_if_needed(max_entries: int = 5000) -> None:
    """Best-effort trim when too many session locks accumulate (unlocked entries only)."""
    if len(SESSION_LOCKS) < max_entries:
        return
    for sid, lock in list(SESSION_LOCKS.items()):
        if not lock.locked():
            SESSION_LOCKS.pop(sid, None)


# ── tool schema helpers ──


def get_all_tool_schemas(identity=None):
    from mirai.core.plugins import get_current_identity, get_edge_scope
    from mirai.core.tool import TOOL_REGISTRY

    if identity is None:
        identity = get_current_identity()

    all_tools = []
    for name, tool_data in TOOL_REGISTRY.items():
        if name not in DISABLED_TOOLS:
            all_tools.append(tool_data["schema"])

    edge_extras = get_edge_scope().filter_edge_tool_schemas(identity, EDGE_TOOLS_REGISTRY, DISABLED_TOOLS)
    all_tools.extend(edge_extras)
    return all_tools


def get_tool_timeout(prefixed_name: str) -> int:
    for edge_tools in EDGE_TOOLS_REGISTRY.values():
        entry = edge_tools.get(prefixed_name)
        if entry and entry.get("timeout") is not None:
            return entry["timeout"]
    return TOOL_CALL_TIMEOUT_DEFAULT


# ── edge tool name splitting ──


def gemini_safe_edge_segment(edge_name: str) -> str:
    """Make a substring safe for Gemini ``function_declarations[].name``.

    Allowed: letters, digits, ``_ . : -`` (see Google GenAI INVALID_ARGUMENT on tool names).
    """
    import re

    s = (edge_name or "").strip()
    if not s:
        return "edge"
    t = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", s)
    t = re.sub(r"_+", "_", t).strip("_")
    if not t:
        return "edge"
    if t[0] in "0123456789.-:":
        t = "e" + t
    return t[:80]


def edge_tool_key_prefix(edge_name: str) -> str:
    """Prefix for tools registered from an edge device, e.g. ``edge_My_Device__``."""
    return f"edge_{gemini_safe_edge_segment(edge_name)}__"


def edge_connection_key(owner_user_id: str | None, edge_name: str) -> str:
    """Registry key for an edge — the EdgeScope plugin chooses the layout."""
    from mirai.core.plugins import get_edge_scope

    return get_edge_scope().connection_key(owner_user_id, edge_name)


def edge_tool_register_prefix(owner_user_id: str | None, edge_name: str) -> str:
    """Tool name prefix for registration (per-user prefix in MT, plain in OSS)."""
    from mirai.core.plugins import get_edge_scope

    return get_edge_scope().tool_register_prefix(owner_user_id, edge_name)


def parse_edge_connection_key(connection_key: str) -> tuple[str | None, str]:
    """Split registry key into (owner_user_id or None, logical edge_name)."""
    if connection_key.startswith("u:"):
        rest = connection_key[2:]
        owner, _, edge = rest.partition("::")
        return (owner or None, edge) if edge else (None, connection_key)
    return None, connection_key


def resolve_edge_for_prefixed_tool_name(prefixed_name: str) -> str | None:
    """Map a full prefixed tool name to the connection key in ``EDGE_TOOLS_REGISTRY``."""
    for en, tools_map in EDGE_TOOLS_REGISTRY.items():
        if prefixed_name in tools_map:
            return en
    return None


def split_edge_prefixed_tool(prefixed_name: str) -> tuple[str | None, str | None]:
    """Parse ``edge_<segment>__<original>`` into (segment, original)."""
    if not prefixed_name.startswith("edge_"):
        return None, None
    rest = prefixed_name[5:]
    if "__" not in rest:
        return None, None
    segment, _, original = rest.partition("__")
    if not segment or not original:
        return None, None
    return segment, original


# ── stream event helper ──


def stream_event(event_type: str, **payload) -> str:
    import json

    return json.dumps({"type": event_type, **payload}) + "\n"
