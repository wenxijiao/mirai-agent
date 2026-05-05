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
from mirai.core.runtime import RuntimeState, get_default_runtime
from mirai.core.runtime.tool_catalog import model_visible_tool_schema as _model_visible_tool_schema
from mirai.logging_config import get_logger

logger = get_logger(__name__)

_runtime: RuntimeState = get_default_runtime()

# Set True after SIGTERM so load balancers stop routing new traffic (see routes lifespan).
server_draining: bool = False

# ── bot singleton ──

bot = None  # set by lifespan; typed as MiraiBot | None
proactive_service = None  # set by lifespan when proactive messaging is enabled

# ── edge connections ──

ACTIVE_CONNECTIONS: dict = _runtime.edge_registry.active_connections
EDGE_TOOLS_REGISTRY: dict = _runtime.edge_registry.tools
PENDING_TOOL_CALLS: dict = _runtime.edge_registry.pending_tool_calls
PENDING_EDGE_OPS: dict = _runtime.edge_registry.pending_file_ops
RELAY_EDGE_PEERS: dict = _runtime.edge_registry.relay_edge_peers

# ── tool policy ──

DISABLED_TOOLS: set[str] = _runtime.tool_policy.disabled_tools
CONFIRMATION_TOOLS: set[str] = _runtime.tool_policy.confirmation_tools
ALWAYS_ALLOWED_TOOLS: set[str] = _runtime.tool_policy.always_allowed_tools
PENDING_CONFIRMATIONS: dict = _runtime.tool_policy.pending_confirmations

# ── sessions ──

SESSION_LOCKS = _runtime.session_locks.locks

# ── timers ──

TIMER_TASKS = _runtime.timer_registry.tasks
# (queue, subscriber_user_id): ``None`` = receive all timers (single-user / compat); else filter by owner.
TIMER_SUBSCRIBERS = _runtime.timer_registry.subscribers

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
    active = _runtime.bot if _runtime.bot is not None else bot
    if active is None:
        raise RuntimeError(
            "Mirai server has no configured chat model. Run `mirai --setup` or start with `mirai --server`."
        )
    return active


def set_runtime(runtime: RuntimeState) -> None:
    """Bind the legacy module facade to a runtime instance."""
    global _runtime, ACTIVE_CONNECTIONS, EDGE_TOOLS_REGISTRY, PENDING_TOOL_CALLS, PENDING_EDGE_OPS
    global RELAY_EDGE_PEERS, DISABLED_TOOLS, CONFIRMATION_TOOLS, ALWAYS_ALLOWED_TOOLS
    global PENDING_CONFIRMATIONS, SESSION_LOCKS, TIMER_TASKS, TIMER_SUBSCRIBERS
    global bot, proactive_service, RELAY_CLIENT, server_draining

    _runtime = runtime
    ACTIVE_CONNECTIONS = runtime.edge_registry.active_connections
    EDGE_TOOLS_REGISTRY = runtime.edge_registry.tools
    PENDING_TOOL_CALLS = runtime.edge_registry.pending_tool_calls
    PENDING_EDGE_OPS = runtime.edge_registry.pending_file_ops
    RELAY_EDGE_PEERS = runtime.edge_registry.relay_edge_peers
    DISABLED_TOOLS = runtime.tool_policy.disabled_tools
    CONFIRMATION_TOOLS = runtime.tool_policy.confirmation_tools
    ALWAYS_ALLOWED_TOOLS = runtime.tool_policy.always_allowed_tools
    PENDING_CONFIRMATIONS = runtime.tool_policy.pending_confirmations
    SESSION_LOCKS = runtime.session_locks.locks
    TIMER_TASKS = runtime.timer_registry.tasks
    TIMER_SUBSCRIBERS = runtime.timer_registry.subscribers
    bot = runtime.bot
    proactive_service = runtime.proactive_service
    RELAY_CLIENT = runtime.relay_client
    server_draining = runtime.server_draining


def get_runtime() -> RuntimeState:
    """Return the runtime currently backing the legacy facade."""
    return _runtime


def set_bot(active_bot) -> None:
    global bot
    bot = active_bot
    _runtime.bot = active_bot


def set_proactive_service(service) -> None:
    global proactive_service
    proactive_service = service
    _runtime.proactive_service = service


def set_relay_client(client) -> None:
    global RELAY_CLIENT
    RELAY_CLIENT = client
    _runtime.relay_client = client


def set_server_draining(value: bool) -> None:
    global server_draining
    server_draining = value
    _runtime.server_draining = value


# ── memory store ──

_memory_store: Memory | None = None


def get_memory_store() -> Memory:
    if _runtime.memory_store is None:
        _runtime.memory_store = Memory(session_id="default")
    return _runtime.memory_store


def get_memory_store_for_identity(identity) -> Memory:
    """Return the Memory store for *identity* via the plugin layer."""
    from mirai.core.plugins import get_memory_factory

    return get_memory_factory().get_for_identity(identity)


# ── session lock ──


def get_session_lock(session_id: str) -> asyncio.Lock:
    return _runtime.session_locks.get(session_id)


def prune_session_locks_if_needed(max_entries: int = 5000) -> None:
    """Best-effort trim when too many session locks accumulate (unlocked entries only)."""
    _runtime.session_locks.prune_if_needed(max_entries)


# ── tool schema helpers ──


def get_all_tool_schemas(identity=None):
    return _runtime.tool_catalog.all_tool_schemas(identity)


def model_visible_tool_schema(schema: dict) -> dict:
    """Compatibility wrapper for provider-visible tool schemas."""
    return _model_visible_tool_schema(schema)


def get_tool_timeout(prefixed_name: str) -> int:
    return _runtime.tool_catalog.tool_timeout(prefixed_name, TOOL_CALL_TIMEOUT_DEFAULT)


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
