"""User-confirmation gate for tool invocations.

Yields a ``tool_confirmation`` event for any invocation that requires
approval, awaits the user's decision via the runtime's pending-confirmation
future map, and persists the policy when the user picks ``always_allow``.

The gate yields ``(event_to_emit | None, accepted_invocation | None)``
tuples so the orchestrator can stream events while keeping confirmation
serial — exactly what the legacy code did, but separated from the rest of
the loop.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

from yumi.core.platform.dispatch.context import ToolInvocation, TurnContext
from yumi.core.platform.http.events import ChatEvent, ToolConfirmationEvent, ToolStatusEvent
from yumi.core.platform.runtime import RuntimeState
from yumi.core.platform.runtime.edge_naming import (
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    parse_edge_connection_key,
)
from yumi.core.platform.tools.trace import record_tool_trace


class ConfirmationGate:
    """Sequential approval check for a batch of prepared tool invocations."""

    CONFIRMATION_TIMEOUT_SECONDS = 120

    def __init__(self, runtime: RuntimeState) -> None:
        self.runtime = runtime

    async def filter(
        self,
        invocations: list[ToolInvocation],
        ctx: TurnContext,
    ) -> AsyncIterator[tuple[ChatEvent | None, ToolInvocation | None]]:
        """Stream events; yield each *approved* invocation alongside any UI events.

        Caller iterates and:
          * forwards every emitted ``event`` to the HTTP layer,
          * collects each ``invocation`` into the run-list.
        """
        policy = self.runtime.tool_policy
        registry = self.runtime.edge_registry.tools

        def _approved(inv: ToolInvocation) -> ToolInvocation:
            # Mark the edge tool as "force-include in subsequent loops" only when
            # confirmation actually granted it — not at prepare-time, otherwise a
            # denied tool would stay sticky in the schema for the rest of the turn.
            if inv.kind == "edge":
                ctx.active_edge_tool_names.add(inv.func_name)
            return inv

        from yumi.core.platform.runtime.assistant_context import personal_store
        from yumi.core.platform.storage.assistant_store import is_group_session, is_personal_session

        personal = personal_store(ctx.owner_uid) if is_personal_session(ctx.session_id) else None

        def record_unavailable(inv: ToolInvocation):
            record_tool_trace(
                session_id=ctx.session_id,
                tool_name=inv.func_name,
                kind=inv.kind,
                edge_name=inv.target_edge,
                display_name=inv.original_tool_name or inv.func_name,
                arguments=inv.args,
                status="denied",
                duration_ms=0,
                result_preview="Tool unavailable: policy changed or conversation restarted.",
                approval="blocked",
                action_summary=inv.action_summary,
                turn_id=ctx.turn_id,
                tool_call_id=inv.tool_call_id,
            )

        for inv in invocations:
            from yumi.core.platform.tools.presentation import action_for_invocation

            locale = "zh" if any("\u4e00" <= char <= "\u9fff" for char in ctx.prompt) else "en"
            if personal:
                locale = (
                    personal.get("response_language", "auto")
                    if personal.get("response_language", "auto") != "auto"
                    else locale
                )
            inv.action_summary = action_for_invocation(inv, self.runtime, locale=locale)
            fn = inv.func_name
            own = personal.get("tools", {}).get(fn, {}) if personal else {}
            stale = (
                personal and personal.get("state", {}).get("session_id") != ctx.session_id and not ctx.timer_callback
            )
            if (
                is_group_session(ctx.session_id)
                or fn in policy.disabled_tools
                or own.get("disabled")
                or own.get("ai_access") == "none"
                or stale
            ):
                ctx.ephemeral_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": inv.tool_call_id,
                        "content": "Tool unavailable: disabled or conversation restarted.",
                        "name": fn,
                    }
                )
                record_unavailable(inv)
                yield ToolStatusEvent(status="error", content=f"Tool '{fn}' is unavailable."), None
                continue
            if (
                fn in policy.always_allowed_tools
                and not own.get("require_confirmation")
                and own.get("ai_access") != "ask"
            ):
                yield None, _approved(inv)
                continue

            edge_requires = False
            if inv.kind == "edge" and inv.target_edge:
                edge_meta = registry.get(inv.target_edge, {}).get(fn)
                if edge_meta:
                    edge_requires = bool(edge_meta.get("require_confirmation"))
            needs_confirm = (
                fn in policy.confirmation_tools
                or edge_requires
                or own.get("require_confirmation", False)
                or own.get("ai_access") == "ask"
            )
            if not needs_confirm:
                yield None, _approved(inv)
                continue

            confirm_id = str(uuid.uuid4())
            confirm_future: asyncio.Future = asyncio.get_running_loop().create_future()
            policy.pending_confirmations[confirm_id] = confirm_future
            policy.confirmation_owners[confirm_id] = ctx.owner_uid

            display_name = inv.original_tool_name if inv.kind == "edge" and inv.original_tool_name else fn
            waiting_since = time.perf_counter()
            yield (
                ToolConfirmationEvent(
                    call_id=confirm_id,
                    tool_name=display_name,
                    full_tool_name=fn,
                    arguments=inv.args,
                    action_summary=inv.action_summary,
                    edge_name=parse_edge_connection_key(inv.target_edge)[1] if inv.target_edge else None,
                    **(
                        {"allow_always": False}
                        if personal and (fn in policy.confirmation_tools or edge_requires)
                        else {}
                    ),
                ),
                None,
            )

            try:
                decision = await asyncio.wait_for(confirm_future, timeout=self.CONFIRMATION_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                decision = "deny"
            finally:
                from yumi.core.platform.observability.turn_inspector import record_confirmation_wait

                record_confirmation_wait(ctx.session_id, int((time.perf_counter() - waiting_since) * 1000))
                policy.pending_confirmations.pop(confirm_id, None)
                policy.confirmation_owners.pop(confirm_id, None)

            if decision == "deny":
                ctx.ephemeral_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": inv.tool_call_id,
                        "content": "Tool execution was denied by the user.",
                        "name": fn,
                    }
                )
                ctx.tool_loop_events.append(
                    {
                        "loop": ctx.loop_count,
                        "tool": fn,
                        "status": "denied",
                        "reason": "user_denied_confirmation",
                    }
                )
                yield (
                    ToolStatusEvent(
                        status="error",
                        content=f"Tool '{display_name}' denied by user.",
                    ),
                    None,
                )
                record_tool_trace(
                    session_id=ctx.session_id,
                    tool_name=fn,
                    kind=inv.kind,
                    edge_name=inv.target_edge,
                    display_name=display_name,
                    arguments=inv.args,
                    status="denied",
                    duration_ms=0,
                    result_preview="User denied confirmation",
                    approval="denied",
                    action_summary=inv.action_summary,
                    turn_id=ctx.turn_id,
                    tool_call_id=inv.tool_call_id,
                )
                continue

            if (
                fn in policy.disabled_tools
                or personal
                and (
                    personal.get("tools", {}).get(fn, {}).get("disabled")
                    or personal.get("tools", {}).get(fn, {}).get("ai_access") == "none"
                    or (personal.get("state", {}).get("session_id") != ctx.session_id and not ctx.timer_callback)
                )
            ):
                record_unavailable(inv)
                ctx.ephemeral_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": inv.tool_call_id,
                        "content": "Tool unavailable: policy changed or conversation restarted.",
                        "name": fn,
                    }
                )
                yield ToolStatusEvent(status="error", content=f"Tool '{fn}' is unavailable."), None
                continue
            if decision == "always_allow":
                if personal:
                    if fn not in policy.confirmation_tools and not edge_requires:
                        with personal.sqlite.connect() as conn:
                            conn.execute("BEGIN IMMEDIATE")
                            saved = personal._read(conn, "tools", {})
                            saved[fn] = {**saved.get(fn, {}), "require_confirmation": False, "ai_access": "auto"}
                            personal._write(conn, "tools", saved)
                else:
                    await self._mark_always_allowed(inv)

            inv.approval = "confirmed"
            yield None, _approved(inv)

    async def _mark_always_allowed(self, inv: ToolInvocation) -> None:
        """Persist an ``always_allow`` decision so the user isn't asked again."""
        policy = self.runtime.tool_policy
        policy.confirmation_tools.discard(inv.func_name)
        policy.always_allowed_tools.add(inv.func_name)

        if inv.kind == "edge":
            from yumi.core.features.edge.api import _push_confirmation_policy_to_edge_peer

            peer = inv.peer
            en = inv.target_edge
            if peer is None or en is None:
                return
            oid, es = parse_edge_connection_key(en)
            tp = edge_tool_register_prefix(oid, es) if oid else edge_tool_key_prefix(es)
            try:
                await _push_confirmation_policy_to_edge_peer(peer, en, tp)
            except Exception:
                pass
        else:
            from yumi.core.features.edge.api import persist_local_tool_confirmation_to_config

            persist_local_tool_confirmation_to_config()
