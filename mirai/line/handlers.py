"""LINE webhook event handling: /chat stream, Flex cards, postbacks (OSS single-user).

Multi-tenant LINE flows (``/link``, ``/usage``, per-user model overrides,
relay-mode chat URLs) live in the ``mirai_enterprise.line`` package and
attach via the plugin system.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException

from mirai.core.api.uploads import MAX_UPLOAD_BYTES, save_uploaded_file
from mirai.core.audit import audit_event
from mirai.core.config import load_saved_model_config
from mirai.core.config.line import (
    get_line_allowed_user_ids,
    get_line_model_candidates,
    line_push_disabled,
)
from mirai.core.connection import DEFAULT_LOCAL_SERVER_URL, ConnectionConfig
from mirai.core.plugins import (
    LOCAL_IDENTITY,
    get_current_identity,
    get_quota_policy,
    get_session_scope,
)
from mirai.core.prompts.http_bridge import (
    format_effective_prompt_reply,
    http_delete_session_prompt,
    http_get_global_system_prompt,
    http_get_session_prompt,
    http_put_session_prompt,
)
from mirai.core.prompts.store import (
    delete_session_prompt,
    get_effective_system_prompt,
    get_session_prompt,
    set_session_prompt,
)
from mirai.line.bridge import chat_connection_config
from mirai.line.client import LineMessagingClient, flex_message, text_message
from mirai.line.flex_builders import (
    file_upload_receipt,
    model_card,
    model_picker_carousel,
    parse_postback,
    tool_confirm_card,
)
from mirai.line.pending import (
    MODEL_PICK_SESSIONS,
    PENDING_TOOL_CONFIRM,
    TIMER_CARD_CTX,
)

_LINE_TEXT_MAX = 5000

_LINE_SYSTEM_HELP = (
    "/system — 本会话系统提示词（仅当前 LINE 会话，非全局）\n\n"
    "/system — 查看当前生效内容\n"
    "/system set <文本…> — 设置本会话覆盖\n"
    "/system reset — 清除覆盖，用服务器全局默认\n"
    "/system help — 本说明\n\n"
    "长文本建议改用 Web 或 API。"
)


def line_session_client_id(line_user_id: str) -> str:
    return f"line_{line_user_id.strip()}"


def _authorized(line_user_id: str) -> bool:
    allowed = get_line_allowed_user_ids()
    if not allowed:
        return True
    return str(line_user_id).strip() in allowed


def _api_url(connection: ConnectionConfig, path: str) -> str:
    return f"{connection.base_url.rstrip('/')}{path}"


def _chat_url(connection: ConnectionConfig) -> str:
    return f"{connection.base_url.rstrip('/')}/chat"


def _split_line_text(text: str) -> list[str]:
    if len(text) <= _LINE_TEXT_MAX:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        chunks.append(rest[:_LINE_TEXT_MAX])
        rest = rest[_LINE_TEXT_MAX:]
    return chunks


async def _post_tool_confirm(connection: ConnectionConfig, call_id: str, decision: str) -> tuple[bool, str]:
    url = _api_url(connection, "/tools/confirm")
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"
    timeout = httpx.Timeout(10.0, read=300.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json={"call_id": call_id, "decision": decision}, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500]
        return True, ""


async def _post_clear_session(connection: ConnectionConfig, session_id: str) -> tuple[bool, str]:
    url = _api_url(connection, f"/clear?session_id={session_id}")
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500]
        return True, ""


async def _line_system_command(
    line_user_id: str,
    client_session_id: str,
    tail: str,
    *,
    use_http: bool,
) -> str:
    t = tail.strip()
    if t.lower() in ("help", "?"):
        return _LINE_SYSTEM_HELP

    parts_sys = t.split(maxsplit=1)
    verb = parts_sys[0].lower() if parts_sys else ""
    arg_rest = parts_sys[1] if len(parts_sys) > 1 else ""

    ident = LOCAL_IDENTITY
    sid = get_session_scope().qualify_session_id(ident, client_session_id)

    if not verb or verb in ("show", "get"):
        if use_http:
            connection = chat_connection_config(line_user_id)
            sp, err = await http_get_session_prompt(connection, client_session_id)
            if err:
                return err
            gp, err2 = await http_get_global_system_prompt(connection)
            if err2:
                return err2
            if sp.get("is_custom") and sp.get("system_prompt"):
                effective = str(sp["system_prompt"])
                label = "本会话自定义"
            else:
                effective = str(gp.get("system_prompt") or "")
                label = "全局默认"
            return format_effective_prompt_reply(effective=effective, source_label=label)

        custom = get_session_prompt(sid)
        eff = get_effective_system_prompt(sid)
        label = "本会话自定义" if custom else "全局默认"
        return format_effective_prompt_reply(effective=eff, source_label=label)

    if verb == "reset":
        if use_http:
            connection = chat_connection_config(line_user_id)
            ok, err = await http_delete_session_prompt(connection, client_session_id)
        else:
            delete_session_prompt(sid)
            ok, err = True, ""
        if ok:
            return "已清除本会话覆盖，将使用服务器全局系统提示词。"
        return f"失败: {err}"

    if verb == "set":
        body = arg_rest.strip()
        if not body:
            return "用法: /system set <提示词内容>"
        if use_http:
            connection = chat_connection_config(line_user_id)
            ok, err = await http_put_session_prompt(connection, client_session_id, body)
        else:
            set_session_prompt(sid, body)
            ok, err = True, ""
        if ok:
            return "已更新本会话系统提示词。"
        return f"失败: {err}"

    return "未知子命令。发送 /system help 查看说明。"


async def _stream_chat_http(line_user_id: str, prompt: str, session_id: str) -> AsyncIterator[dict[str, Any]]:
    connection = chat_connection_config(line_user_id)
    url = _chat_url(connection)
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"
    timeout = httpx.Timeout(10.0, read=600.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            url,
            json={"prompt": prompt, "session_id": session_id},
            headers=headers,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                yield {"type": "error", "content": f"HTTP {response.status_code}: {body[:500]}"}
                return
            buffer = ""
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        yield event


async def _stream_chat_direct(line_user_id: str, prompt: str, session_id: str) -> AsyncIterator[dict[str, Any]]:
    ident = get_current_identity()
    quota = get_quota_policy()
    allowed, qerr = quota.check_chat_allowed(ident)
    if not allowed:
        yield {"type": "error", "content": qerr or "quota exceeded"}
        return
    tok_ok, tok_err = quota.check_token_quota(ident)
    if not tok_ok:
        yield {"type": "error", "content": tok_err or "token quota exceeded"}
        return
    sid = get_session_scope().qualify_session_id(ident, session_id)
    quota.record_chat_turn(ident)
    audit_event("chat_request", ident.user_id, session_id=sid, source="line", line_user_id=line_user_id)
    from mirai.core.api.chat import generate_chat_events

    async for ev in generate_chat_events(prompt, sid, think=False):
        yield ev


async def stream_line_chat(
    line_user_id: str,
    prompt: str,
    session_id: str,
    *,
    use_http: bool,
) -> AsyncIterator[dict[str, Any]]:
    if use_http:
        async for ev in _stream_chat_http(line_user_id, prompt, session_id):
            yield ev
    else:
        async for ev in _stream_chat_direct(line_user_id, prompt, session_id):
            yield ev


async def _send_messages(
    line_client: LineMessagingClient,
    reply_token: str | None,
    user_id: str,
    messages: list[dict[str, Any]],
    *,
    started_monotonic: float,
    prefer_push: bool = False,
) -> None:
    if line_push_disabled() or not messages:
        return
    use_push = prefer_push or (not reply_token)
    if not use_push:
        elapsed = __import__("time").monotonic() - started_monotonic
        if elapsed > 25.0:
            use_push = True
    if use_push:
        await line_client.push_message(user_id, messages)
        return
    try:
        await line_client.reply_message(reply_token or "", messages)
    except Exception:
        await line_client.push_message(user_id, messages)


async def _get_model_dict(line_user_id: str, *, use_http: bool) -> dict[str, Any] | None:
    if use_http:
        connection = chat_connection_config(line_user_id)
        url = _api_url(connection, "/config/model")
        headers = connection.auth_headers()
        timeout = httpx.Timeout(10.0, read=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers)
            if r.status_code >= 400:
                return None
            return r.json()
    cfg = load_saved_model_config()
    from mirai.core.config import get_api_credentials

    creds = get_api_credentials()
    return {
        "chat_provider": cfg.chat_provider,
        "chat_model": cfg.chat_model or "",
        "embedding_provider": cfg.embedding_provider,
        "embedding_model": cfg.embedding_model or "",
        "openai_api_key_saved": bool(cfg.openai_api_key and str(cfg.openai_api_key).strip()),
        "gemini_api_key_saved": bool(cfg.gemini_api_key and str(cfg.gemini_api_key).strip()),
        "claude_api_key_saved": bool(cfg.claude_api_key and str(cfg.claude_api_key).strip()),
        "openai_api_key_effective": bool(creds.get("openai_api_key")),
        "gemini_api_key_effective": bool(creds.get("gemini_api_key")),
        "claude_api_key_effective": bool(creds.get("claude_api_key")),
    }


async def _apply_chat_model(line_user_id: str, model_name: str, *, use_http: bool) -> tuple[bool, str]:
    name = (model_name or "").strip()
    if not name:
        return False, "empty model"
    if use_http:
        connection = chat_connection_config(line_user_id)
        headers = connection.auth_headers()
        timeout = httpx.Timeout(10.0, read=60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            url = _api_url(connection, "/config/model")
            r = await client.put(
                url,
                headers={**headers, "Content-Type": "application/json"},
                json={"chat_model": name},
            )
            if r.status_code >= 400:
                return False, r.text[:500]
        return True, ""

    from mirai.core.config import save_model_config

    cfg = load_saved_model_config()
    cfg.chat_model = name
    save_model_config(cfg)
    return True, ""


async def handle_line_message_event(
    event: dict[str, Any],
    line_client: LineMessagingClient,
    *,
    use_http: bool,
) -> None:
    reply_tok = event.get("replyToken")
    src = event.get("source") or {}
    if src.get("type") != "user":
        return
    user_id = str(src.get("userId") or "").strip()
    if not user_id or not _authorized(user_id):
        return

    msg = event.get("message") or {}
    mtype = msg.get("type")
    started = __import__("time").monotonic()
    session_id = line_session_client_id(user_id)
    connection = chat_connection_config(user_id)

    async def reply_text(text: str, *, push: bool = False) -> None:
        parts = _split_line_text(text)
        msgs = [text_message(p) for p in parts]
        await _send_messages(line_client, reply_tok, user_id, msgs, started_monotonic=started, prefer_push=push)

    # ── commands (text) ──
    if mtype == "text":
        raw = (msg.get("text") or "").strip()
        lower = raw.lower()
        if lower in ("/help", "/start", "help"):
            await reply_text(
                "Mirai LINE 桥接\n\n"
                "发消息即可对话（支持图片/文件）。\n"
                "命令：\n"
                "/clear — 清除本会话\n"
                "/model — 查看/切换模型\n"
                "/system — 本会话系统提示词（见 /system help）\n"
                "/help — 本说明"
            )
            return
        if lower.startswith("/clear"):
            ok, err = await _post_clear_session(connection, session_id)
            if ok:
                await reply_text("会话已清除。")
            else:
                await reply_text(f"清除失败: {err}")
            return
        if lower.startswith("/model"):
            cfg = await _get_model_dict(user_id, use_http=use_http)
            if not cfg:
                await reply_text("无法读取模型配置。")
                return
            pick_sid = uuid.uuid4().hex[:8]
            bubble = model_card(
                str(cfg.get("chat_provider", "?")),
                str(cfg.get("chat_model", "?")),
                str(cfg.get("embedding_provider", "?")),
                str(cfg.get("embedding_model", "?")),
                pick_sid,
            )
            MODEL_PICK_SESSIONS[pick_sid] = list(get_line_model_candidates())
            msg_flex = flex_message("Model", bubble)
            await _send_messages(
                line_client,
                reply_tok,
                user_id,
                [msg_flex],
                started_monotonic=started,
            )
            return
        if raw.lower().startswith("/system"):
            tail = raw[len("/system"):].strip()
            out = await _line_system_command(user_id, session_id, tail, use_http=use_http)
            await reply_text(out)
            return

        prompt = raw
        if not prompt:
            return

        accumulated: list[str] = []
        async for ev in stream_line_chat(user_id, prompt, session_id, use_http=use_http):
            et = ev.get("type")
            if et == "text":
                accumulated.append(str(ev.get("content", "")))
            elif et == "tool_confirmation":
                call_id = str(ev.get("call_id", ""))
                tool_name = str(ev.get("tool_name", ""))
                args = ev.get("arguments") if isinstance(ev.get("arguments"), dict) else {}
                short_id = uuid.uuid4().hex[:8]
                fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
                PENDING_TOOL_CONFIRM[short_id] = fut
                args_preview = json.dumps(args, ensure_ascii=False)[:800]
                bubble = tool_confirm_card(tool_name, args_preview, short_id)
                try:
                    await line_client.push_message(user_id, [flex_message("Confirm", bubble)])
                except Exception:
                    pass
                try:
                    action = await asyncio.wait_for(fut, timeout=600.0)
                except asyncio.TimeoutError:
                    action = "deny"
                finally:
                    PENDING_TOOL_CONFIRM.pop(short_id, None)
                decision_map = {"deny": "deny", "allow": "allow", "always": "always_allow"}
                dkey = decision_map.get(action, "deny")
                ok_c, err_c = await _post_tool_confirm(connection, call_id, dkey)
                if not ok_c:
                    await reply_text(f"确认失败: {err_c}", push=True)
            elif et == "error":
                await reply_text(f"错误: {ev.get('content', 'Unknown')}", push=True)

        final_text = "".join(accumulated)
        msgs: list[dict[str, Any]] = []
        for chunk in _split_line_text(final_text) if final_text else []:
            msgs.append(text_message(chunk))
        if msgs:
            await _send_messages(line_client, reply_tok, user_id, msgs, started_monotonic=started)
        return

    # Non-text: image / file
    if mtype in ("image", "file"):
        parts: list[str] = []
        ok_media = await _append_line_media_to_parts(
            msg, line_client, user_id, session_id, parts
        )
        if not ok_media or not parts:
            await reply_text("无法处理该媒体。")
            return
        prompt = "\n".join(parts)
        media_receipts: list[dict[str, Any]] = []
        if parts and (parts[0].startswith("/") or parts[0].startswith("~")):
            p0 = parts[0]
            try:
                sz = __import__("pathlib").Path(p0).stat().st_size
                name = __import__("os").path.basename(p0)
                media_receipts.append(flex_message("File", file_upload_receipt(name, sz, None)))
            except OSError:
                pass
        accumulated: list[str] = []
        async for ev in stream_line_chat(user_id, prompt, session_id, use_http=use_http):
            et = ev.get("type")
            if et == "text":
                accumulated.append(str(ev.get("content", "")))
            elif et == "tool_confirmation":
                call_id = str(ev.get("call_id", ""))
                tool_name = str(ev.get("tool_name", ""))
                args = ev.get("arguments") if isinstance(ev.get("arguments"), dict) else {}
                short_id = uuid.uuid4().hex[:8]
                fut = asyncio.get_running_loop().create_future()
                PENDING_TOOL_CONFIRM[short_id] = fut
                args_preview = json.dumps(args, ensure_ascii=False)[:800]
                bubble = tool_confirm_card(tool_name, args_preview, short_id)
                try:
                    await line_client.push_message(user_id, [flex_message("Confirm", bubble)])
                except Exception:
                    pass
                try:
                    action = await asyncio.wait_for(fut, timeout=600.0)
                except asyncio.TimeoutError:
                    action = "deny"
                finally:
                    PENDING_TOOL_CONFIRM.pop(short_id, None)
                decision_map = {"deny": "deny", "allow": "allow", "always": "always_allow"}
                dkey = decision_map.get(action, "deny")
                ok_c, err_c = await _post_tool_confirm(connection, call_id, dkey)
                if not ok_c:
                    await reply_text(f"确认失败: {err_c}", push=True)
            elif et == "error":
                await reply_text(f"错误: {ev.get('content', 'Unknown')}", push=True)
        final_text = "".join(accumulated)
        msgs: list[dict[str, Any]] = list(media_receipts)
        for chunk in _split_line_text(final_text) if final_text else []:
            msgs.append(text_message(chunk))
        if msgs:
            await _send_messages(line_client, reply_tok, user_id, msgs, started_monotonic=started)
        return

    await reply_text("暂不支持该消息类型（请发文本/图片/文件）。")


async def _append_line_media_to_parts(
    msg: dict[str, Any],
    line_client: LineMessagingClient,
    line_user_id: str,
    session_id: str,
    parts: list[str],
) -> bool:
    mtype = msg.get("type")
    mid = msg.get("id")
    if not mid:
        return True
    try:
        data = await line_client.get_message_content(str(mid))
    except Exception as exc:
        parts.clear()
        parts.append(f"(download failed: {exc})")
        return False
    if len(data) > MAX_UPLOAD_BYTES:
        parts.clear()
        parts.append(f"文件过大（最大 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB）")
        return False
    if mtype == "image":
        name = f"line_image_{mid}.jpg"
    else:
        name = str(msg.get("fileName") or f"line_file_{mid}")
    try:
        res = save_uploaded_file(session_id, name, data, owner_user_id=None)
    except HTTPException as exc:
        parts.clear()
        parts.append(str(exc.detail))
        return False
    parts.append(str(res.get("path", "")))
    # silence unused-arg lint while keeping stable signature for enterprise overrides
    _ = line_user_id
    return True


async def handle_line_postback_event(
    event: dict[str, Any],
    line_client: LineMessagingClient,
    *,
    use_http: bool,
) -> None:
    reply_tok = event.get("replyToken")
    src = event.get("source") or {}
    if src.get("type") != "user":
        return
    user_id = str(src.get("userId") or "").strip()
    if not user_id or not _authorized(user_id):
        return
    data = str((event.get("postback") or {}).get("data") or "")
    parsed = parse_postback(data)
    if not parsed:
        return
    verb, short_id, arg = parsed
    started = __import__("time").monotonic()

    async def reply_text(text: str, *, push: bool = False) -> None:
        msgs = [text_message(t) for t in _split_line_text(text)]
        await _send_messages(line_client, reply_tok, user_id, msgs, started_monotonic=started, prefer_push=push)

    if verb == "tool_confirm":
        fut = PENDING_TOOL_CONFIRM.get(short_id)
        if fut is None or fut.done():
            await reply_text("确认已过期或已使用。")
            return
        if arg not in ("deny", "allow", "always"):
            arg = "deny"
        fut.set_result(arg)
        await reply_text("已记录选择。")
        return

    if verb == "model_switch":
        if arg == "__open__":
            candidates = MODEL_PICK_SESSIONS.get(short_id) or list(get_line_model_candidates())
            car = model_picker_carousel(candidates, short_id)
            await _send_messages(
                line_client,
                reply_tok,
                user_id,
                [flex_message("Pick model", car)],
                started_monotonic=started,
            )
            return
        try:
            idx = int(arg)
        except ValueError:
            await reply_text("无效选项。")
            return
        candidates = MODEL_PICK_SESSIONS.get(short_id) or []
        if idx < 0 or idx >= len(candidates):
            await reply_text("无效模型索引。")
            return
        model_name = candidates[idx]
        ok, err = await _apply_chat_model(user_id, model_name, use_http=use_http)
        if ok:
            await reply_text(f"已切换 chat 模型为: {model_name}")
        else:
            await reply_text(f"切换失败: {err}")
        return

    if verb == "timer_snooze":
        ctx = TIMER_CARD_CTX.get(short_id)
        if not ctx:
            await reply_text("定时器上下文已过期。")
            return
        try:
            delay = int(arg)
        except ValueError:
            delay = 300
        from mirai.core.api.timers import schedule_timer

        schedule_timer(
            "line_snooze_" + uuid.uuid4().hex[:8],
            delay,
            str(ctx.get("description", "")),
            str(ctx.get("qualified_session_id", ctx.get("session_id", ""))),
        )
        await reply_text(f"已延后约 {max(1, delay // 60)} 分钟。")
        return

    if verb == "timer_rerun":
        ctx = TIMER_CARD_CTX.get(short_id)
        if not ctx:
            await reply_text("定时器上下文已过期。")
            return
        client_sid = str(ctx.get("client_session_id", line_session_client_id(user_id)))
        description = str(ctx.get("description", ""))
        prompt = (
            f"[Timer expired — scheduled action]\n"
            f"Planned task: {description}\n"
            f"Now execute it: call tools as needed, then answer the user in the same language."
        )
        line_uid = user_id
        accumulated: list[str] = []
        async for ev in stream_line_chat(line_uid, prompt, client_sid, use_http=use_http):
            if ev.get("type") == "text":
                accumulated.append(str(ev.get("content", "")))
            elif ev.get("type") == "error":
                await reply_text(str(ev.get("content", "error")), push=True)
        final = "".join(accumulated)
        if final:
            msgs = [text_message(t) for t in _split_line_text(final)]
            await _send_messages(line_client, None, user_id, msgs, started_monotonic=started, prefer_push=True)
        return


async def dispatch_line_webhook(
    body: bytes,
    x_line_signature: str | None,
    *,
    use_http: bool,
) -> None:
    from mirai.core.config.line import get_line_channel_access_token, get_line_channel_secret

    secret = get_line_channel_secret()
    token = get_line_channel_access_token()
    if not secret:
        raise RuntimeError("LINE_CHANNEL_SECRET not configured")
    from mirai.line.client import verify_line_signature

    if not verify_line_signature(secret, body, x_line_signature):
        raise PermissionError("invalid LINE signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid webhook json: {exc}") from exc

    events = payload.get("events") or []
    if not isinstance(events, list):
        return

    line_client = LineMessagingClient(token or "")
    for event in events:
        if not isinstance(event, dict):
            continue
        et = event.get("type")
        try:
            if et == "message":
                await handle_line_message_event(event, line_client, use_http=use_http)
            elif et == "postback":
                await handle_line_postback_event(event, line_client, use_http=use_http)
            elif et == "follow":
                reply_tok = event.get("replyToken")
                src = event.get("source") or {}
                uid = str(src.get("userId") or "")
                if uid and line_client.token_configured and not line_push_disabled():
                    try:
                        await line_client.reply_message(
                            reply_tok or "",
                            [
                                text_message(
                                    "Mirai LINE 已就绪。发 /help 查看命令。"
                                )
                            ],
                        )
                    except Exception:
                        pass
        except Exception:
            from mirai.logging_config import get_logger

            get_logger(__name__).exception("LINE event handler error")


# silence unused-import lint while keeping the symbol importable for enterprise overrides
_ = (DEFAULT_LOCAL_SERVER_URL, os)
