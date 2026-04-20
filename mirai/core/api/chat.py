"""Chat generation logic extracted from api.py."""

import asyncio
import json
import time
import uuid

from json_repair import repair_json
from mirai.core.api.chat_context import reset_chat_owner_user_id, set_chat_owner_user_id
from mirai.core.api.edge import _push_confirmation_policy_to_edge_peer, persist_local_tool_confirmation_to_config
from mirai.core.api.state import (
    ACTIVE_CONNECTIONS,
    ALWAYS_ALLOWED_TOOLS,
    CONFIRMATION_TOOLS,
    EDGE_TOOLS_REGISTRY,
    LOCAL_TOOL_TIMEOUT_DEFAULT,
    MAX_TOOL_CALL_FORMAT_RETRIES,
    MAX_TOOL_LOOPS,
    PENDING_CONFIRMATIONS,
    PENDING_TOOL_CALLS,
    SESSION_LOCKS,
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    get_all_tool_schemas,
    get_session_lock,
    get_tool_timeout,
    parse_edge_connection_key,
    prune_session_locks_if_needed,
    resolve_edge_for_prefixed_tool_name,
)
from mirai.core.plugins import (
    SINGLE_USER_ID,
    get_bot_pool,
    get_current_identity,
    get_quota_policy,
    get_session_scope,
)
from mirai.core.tool import TOOL_REGISTRY, execute_registered_tool
from mirai.core.tool_call_normalize import normalize_tool_calls, tool_call_format_retry_user_content
from mirai.core.tool_trace import record_tool_trace
from mirai.logging_config import get_logger

_chat_log = get_logger(__name__)


def _summarize_tool_args(args: dict | None, max_len: int = 500) -> str:
    if not args:
        return "{}"
    try:
        s = json.dumps(args, ensure_ascii=False)
    except Exception:
        s = str(args)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _canonical_local_tool_name(raw: str) -> str:
    """Map model-emitted names to ``TOOL_REGISTRY`` keys (case, ``functions.`` prefix)."""
    fn = (raw or "").strip()
    if not fn:
        return fn
    if fn.startswith("functions."):
        fn = fn[len("functions.") :]
    if fn.startswith("edge_"):
        return fn
    if fn in TOOL_REGISTRY:
        return fn
    lower = fn.lower()
    if lower in TOOL_REGISTRY:
        return lower
    return fn


def _tail_assistant_tool_span(messages: list[dict]) -> tuple[int, int] | None:
    """Return ``[start, end)`` indices for the last ``assistant``+``tool_calls`` and its ``tool`` replies.

    Gemini (and strict OpenAI-style replay) require that persisted tool turns are not duplicated
    in ``ephemeral_messages`` on the next loop iteration; removing this span after persist avoids
    ``model`` (function call) turns that do not immediately follow ``user`` or ``function`` roles.
    """
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        j = i + 1
        while j < len(messages) and messages[j].get("role") == "tool":
            j += 1
        return (i, j)
    return None


def _persist_tool_ephemeral_tail(ephemeral_messages: list, session_id: str, bot) -> None:
    span = _tail_assistant_tool_span(ephemeral_messages)
    if not span:
        return
    i, j = span
    turn = [dict(ephemeral_messages[k]) for k in range(i, j)]
    bot.session_memory(session_id).persist_openai_messages(turn)
    del ephemeral_messages[i:j]


async def generate_chat_events(prompt: str, session_id: str, think: bool = False):
    owner_uid = get_session_scope().owner_user_from_session_id(session_id)
    owner_token = set_chat_owner_user_id(owner_uid)
    total_prompt_tokens = 0
    total_completion_tokens = 0
    usage_model = ""
    active_bot = None
    try:
        lock = get_session_lock(session_id)
        await lock.acquire()
        try:
            ident = get_current_identity()
            if ident.user_id not in (SINGLE_USER_ID, owner_uid):
                yield {
                    "type": "error",
                    "code": "FORBIDDEN",
                    "content": "Session does not belong to the current user",
                }
                return

            active_bot = await get_bot_pool().get_bot_for_session_owner(owner_uid)
            current_prompt = prompt
            ephemeral_messages = []
            loop_count = 0
            tool_format_retries = 0

            while True:
                loop_count += 1
                if loop_count > MAX_TOOL_LOOPS:
                    yield {
                        "type": "error",
                        "content": "System: Maximum tool execution iterations reached. Stopping to prevent infinite loops.",
                    }
                    break
                all_tools = get_all_tool_schemas(get_current_identity())
                stream = active_bot.chat_stream(
                    prompt=current_prompt,
                    session_id=session_id,
                    tools=all_tools if all_tools else None,
                    ephemeral_messages=ephemeral_messages,
                    think=think,
                )

                tool_calls_to_process = None
                streamed_text_before_tools = ""

                async for chunk in stream:
                    if chunk.get("type") == "usage":
                        total_prompt_tokens += int(chunk.get("prompt_tokens", 0) or 0)
                        total_completion_tokens += int(chunk.get("completion_tokens", 0) or 0)
                        if chunk.get("model"):
                            usage_model = str(chunk["model"])
                        continue
                    if chunk["type"] == "text":
                        streamed_text_before_tools += chunk["content"]
                        yield {"type": "text", "content": chunk["content"]}
                    elif chunk["type"] == "thought":
                        yield {"type": "thought", "content": chunk["content"]}
                    elif chunk["type"] == "tool_call":
                        tool_calls_to_process = chunk["tool_calls"]
                        break

                if not tool_calls_to_process:
                    tool_format_retries = 0
                    break

                tcalls = normalize_tool_calls(tool_calls_to_process)
                if not tcalls:
                    tool_format_retries += 1
                    if tool_format_retries > MAX_TOOL_CALL_FORMAT_RETRIES:
                        yield {
                            "type": "error",
                            "content": (
                                "Model returned tool_calls that could not be parsed into a usable format "
                                f"after {MAX_TOOL_CALL_FORMAT_RETRIES} automatic re-tries."
                            ),
                        }
                        break
                    ephemeral_messages.append(
                        {
                            "role": "user",
                            "content": tool_call_format_retry_user_content(tool_calls_to_process),
                        }
                    )
                    yield {
                        "type": "tool_status",
                        "status": "error",
                        "content": (
                            f"Tool call format invalid (attempt {tool_format_retries}/"
                            f"{MAX_TOOL_CALL_FORMAT_RETRIES}); asking the model to regenerate."
                        ),
                    }
                    continue

                tool_format_retries = 0

                ephemeral_messages.append(
                    {"role": "assistant", "content": streamed_text_before_tools, "tool_calls": tcalls}
                )

                prepared: list[dict] = []
                for tc in tcalls:
                    raw_call_name = str(tc["function"]["name"]).strip()
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            try:
                                args = repair_json(args, return_objects=True)
                                if not isinstance(args, dict):
                                    raise ValueError("Repaired JSON is not an object")
                            except Exception:
                                error_msg = (
                                    f"Error: Invalid JSON in arguments for tool '{raw_call_name}'. "
                                    f"Raw input: {args!r}. Please retry with valid JSON."
                                )
                                ephemeral_messages.append({"role": "tool", "content": error_msg, "name": raw_call_name})
                                yield {
                                    "type": "tool_status",
                                    "status": "error",
                                    "content": f"Tool '{raw_call_name}': invalid JSON arguments",
                                }
                                continue

                    func_name = _canonical_local_tool_name(raw_call_name)
                    entry: dict = {
                        "func_name": func_name,
                        "tool_message_name": raw_call_name,
                        "args": args,
                    }

                    if func_name in TOOL_REGISTRY:
                        if (
                            func_name in ("set_timer", "schedule_task")
                            and args.get("session_id", "default") == "default"
                        ):
                            args["session_id"] = session_id
                        entry["kind"] = "local"
                    else:
                        target_edge = None
                        original_tool_name = func_name
                        resolved = resolve_edge_for_prefixed_tool_name(func_name)
                        if resolved is not None:
                            target_edge = resolved
                            owner_id, edge_simple = parse_edge_connection_key(resolved)
                            prefix = (
                                edge_tool_register_prefix(owner_id, edge_simple)
                                if owner_id
                                else edge_tool_key_prefix(edge_simple)
                            )
                            if func_name.startswith(prefix):
                                original_tool_name = func_name[len(prefix) :]

                        if not target_edge:
                            if func_name.startswith("edge_"):
                                err_detail = (
                                    f"Tool '{func_name}' targets an edge device that is offline or not connected."
                                )
                            else:
                                err_detail = (
                                    f"Tool '{raw_call_name}' is not registered on this Mirai server "
                                    f"(resolved as '{func_name}'). Restart the server after upgrading, "
                                    "and check the Tools page that it is not disabled."
                                )
                            ephemeral_messages.append(
                                {"role": "tool", "content": f"Error: {err_detail}", "name": raw_call_name}
                            )
                            yield {"type": "tool_status", "status": "error", "content": err_detail}
                            continue

                        peer = ACTIVE_CONNECTIONS.get(target_edge)
                        if peer is None:
                            ephemeral_messages.append(
                                {
                                    "role": "tool",
                                    "content": "Error: Device offline or tool not found.",
                                    "name": raw_call_name,
                                }
                            )
                            yield {
                                "type": "tool_status",
                                "status": "error",
                                "content": f"Edge device '{target_edge}' went offline before tool execution started.",
                            }
                            continue

                        entry["kind"] = "edge"
                        entry["target_edge"] = target_edge
                        entry["original_tool_name"] = original_tool_name
                        entry["peer"] = peer

                    prepared.append(entry)

                if not prepared:
                    _persist_tool_ephemeral_tail(ephemeral_messages, session_id, active_bot)
                    current_prompt = None
                    continue

                confirmed_prepared: list[dict] = []
                for entry in prepared:
                    fn = entry["func_name"]
                    if fn in ALWAYS_ALLOWED_TOOLS:
                        confirmed_prepared.append(entry)
                        continue

                    edge_requires = False
                    if entry["kind"] == "edge":
                        edge_meta = EDGE_TOOLS_REGISTRY.get(entry["target_edge"], {}).get(fn)
                        if edge_meta:
                            edge_requires = bool(edge_meta.get("require_confirmation"))

                    needs_confirm = fn in CONFIRMATION_TOOLS or edge_requires
                    if not needs_confirm:
                        confirmed_prepared.append(entry)
                        continue

                    confirm_id = str(uuid.uuid4())
                    confirm_future: asyncio.Future = asyncio.get_running_loop().create_future()
                    PENDING_CONFIRMATIONS[confirm_id] = confirm_future

                    display_name = fn
                    if entry["kind"] == "edge" and "original_tool_name" in entry:
                        display_name = entry["original_tool_name"]

                    yield {
                        "type": "tool_confirmation",
                        "call_id": confirm_id,
                        "tool_name": display_name,
                        "full_tool_name": fn,
                        "arguments": entry["args"],
                    }

                    try:
                        decision = await asyncio.wait_for(confirm_future, timeout=120)
                    except asyncio.TimeoutError:
                        decision = "deny"
                    finally:
                        PENDING_CONFIRMATIONS.pop(confirm_id, None)

                    if decision == "deny":
                        ephemeral_messages.append(
                            {"role": "tool", "content": "Tool execution was denied by the user.", "name": fn}
                        )
                        yield {
                            "type": "tool_status",
                            "status": "error",
                            "content": f"Tool '{display_name}' denied by user.",
                        }
                        record_tool_trace(
                            session_id=session_id,
                            tool_name=fn,
                            kind=entry["kind"],
                            edge_name=entry.get("target_edge"),
                            display_name=display_name,
                            arguments=entry["args"],
                            status="denied",
                            duration_ms=0,
                            result_preview="User denied confirmation",
                        )
                        continue
                    if decision == "always_allow":
                        CONFIRMATION_TOOLS.discard(fn)
                        ALWAYS_ALLOWED_TOOLS.add(fn)
                        if entry["kind"] == "edge":
                            peer = entry.get("peer")
                            en = entry.get("target_edge")
                            if peer and en:
                                oid, es = parse_edge_connection_key(en)
                                tp = edge_tool_register_prefix(oid, es) if oid else edge_tool_key_prefix(es)
                                try:
                                    await _push_confirmation_policy_to_edge_peer(peer, en, tp)
                                except Exception:
                                    pass
                        else:
                            persist_local_tool_confirmation_to_config()
                    confirmed_prepared.append(entry)

                prepared = confirmed_prepared

                if not prepared and ephemeral_messages:
                    _persist_tool_ephemeral_tail(ephemeral_messages, session_id, active_bot)
                    current_prompt = None
                    continue

                async def _run_one(entry: dict) -> dict:
                    func_name = entry["func_name"]
                    args = entry["args"]
                    if entry["kind"] == "local":
                        try:
                            result = await asyncio.wait_for(
                                execute_registered_tool(func_name, args),
                                timeout=LOCAL_TOOL_TIMEOUT_DEFAULT,
                            )
                            return {"func_name": func_name, "result": str(result), "status": "success"}
                        except asyncio.TimeoutError:
                            return {
                                "func_name": func_name,
                                "result": "Error: Local tool execution timed out.",
                                "status": "error",
                            }
                        except Exception as exc:
                            return {
                                "func_name": func_name,
                                "result": f"Error: Local tool execution failed: {exc}",
                                "status": "error",
                            }
                    else:
                        target_edge = entry["target_edge"]
                        original_tool_name = entry["original_tool_name"]
                        peer = entry["peer"]
                        call_id = str(uuid.uuid4())
                        future = asyncio.get_running_loop().create_future()
                        PENDING_TOOL_CALLS[call_id] = {
                            "future": future,
                            "edge_name": target_edge,
                            "peer": peer,
                        }
                        try:
                            await peer.send_json(
                                {
                                    "type": "tool_call",
                                    "name": original_tool_name,
                                    "arguments": args,
                                    "call_id": call_id,
                                }
                            )
                            result = await asyncio.wait_for(future, timeout=get_tool_timeout(func_name))
                            return {
                                "func_name": func_name,
                                "result": str(result),
                                "status": "success",
                                "original_tool_name": original_tool_name,
                                "target_edge": target_edge,
                            }
                        except asyncio.TimeoutError:
                            try:
                                await peer.send_json({"type": "cancel", "call_id": call_id})
                            except Exception:
                                pass
                            return {
                                "func_name": func_name,
                                "result": "Error: Tool execution timed out.",
                                "status": "error",
                                "original_tool_name": original_tool_name,
                                "target_edge": target_edge,
                            }
                        except asyncio.CancelledError:
                            try:
                                await peer.send_json({"type": "cancel", "call_id": call_id})
                            except Exception:
                                pass
                            raise
                        except Exception as exc:
                            return {
                                "func_name": func_name,
                                "result": f"Error: Tool execution failed: {exc}",
                                "status": "error",
                                "original_tool_name": original_tool_name,
                                "target_edge": target_edge,
                            }
                        finally:
                            PENDING_TOOL_CALLS.pop(call_id, None)

                async def _timed_run_one(entry: dict) -> dict:
                    t0 = time.perf_counter()
                    r = await _run_one(entry)
                    dt_ms = int((time.perf_counter() - t0) * 1000)
                    disp = entry["func_name"]
                    if entry["kind"] == "edge":
                        disp = entry.get("original_tool_name", entry["func_name"])
                    record_tool_trace(
                        session_id=session_id,
                        tool_name=entry["func_name"],
                        kind=entry["kind"],
                        edge_name=entry.get("target_edge"),
                        display_name=disp,
                        arguments=entry["args"],
                        status=r.get("status", "error"),
                        duration_ms=dt_ms,
                        result_preview=str(r.get("result", ""))[:500],
                    )
                    return r

                for entry in prepared:
                    fn = entry["func_name"]
                    if entry["kind"] == "local":
                        _chat_log.info(
                            "Tool call: %s session_id=%s args=%s",
                            fn,
                            session_id,
                            _summarize_tool_args(entry.get("args")),
                        )
                        yield {"type": "tool_status", "status": "running", "content": f"Running local tool '{fn}'..."}
                    else:
                        yield {
                            "type": "tool_status",
                            "status": "running",
                            "content": f"Calling '{entry['original_tool_name']}' on edge device '{entry['target_edge']}'...",
                        }

                results = await asyncio.gather(*[_timed_run_one(e) for e in prepared])

                for entry, r in zip(prepared, results):
                    fn = r["func_name"]
                    tool_nm = entry.get("tool_message_name", fn)
                    if r["status"] == "success":
                        label = fn
                        if "original_tool_name" in r:
                            label = f"'{r['original_tool_name']}' on '{r['target_edge']}'"
                        else:
                            label = f"'{fn}'"
                        yield {
                            "type": "tool_status",
                            "status": "success",
                            "content": f"Tool {label} finished successfully.",
                        }
                    else:
                        label = fn
                        if "original_tool_name" in r:
                            label = f"'{r['original_tool_name']}' on '{r['target_edge']}'"
                        else:
                            label = f"'{fn}'"
                        yield {"type": "tool_status", "status": "error", "content": f"Tool {label} failed."}

                ephemeral_messages.append({"role": "tool", "content": r["result"], "name": tool_nm})

            _persist_tool_ephemeral_tail(ephemeral_messages, session_id, active_bot)
            current_prompt = None

        except Exception as exc:
            _chat_log.exception("Chat pipeline failed session_id=%s", session_id)
            yield {
                "type": "error",
                "code": "MIRAI_CHAT_PIPELINE_FAILED",
                "content": f"Chat request failed: {exc}",
            }
        finally:
            try:
                if active_bot is not None:
                    ident = get_current_identity()
                    if ident.user_id != SINGLE_USER_ID and ident.user_id == owner_uid:
                        get_quota_policy().record_chat_tokens(
                            ident,
                            total_prompt_tokens,
                            total_completion_tokens,
                            model=usage_model or active_bot.model_name,
                        )
            except Exception:
                _chat_log.debug("record_chat_tokens skipped", exc_info=True)
            prune_session_locks_if_needed()
            lock.release()
    finally:
        reset_chat_owner_user_id(owner_token)


async def clear_session(session_id: str):
    owner = get_session_scope().owner_user_from_session_id(session_id)
    bot = await get_bot_pool().get_bot_for_session_owner(owner)
    bot.clear_memory(session_id)
    SESSION_LOCKS.pop(session_id, None)
    return {"status": "success", "message": f"Cleared memory for session: {session_id}"}
