"""Telegram client for Mirai: forwards messages to POST /chat (NDJSON) and handles tool confirmations."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import HTTPException

from mirai.core.api.uploads import MAX_UPLOAD_BYTES, save_uploaded_file
from mirai.core.config import get_telegram_allowed_user_ids, get_telegram_bot_token
from mirai.core.connection import DEFAULT_LOCAL_SERVER_URL, ConnectionConfig
from mirai.core.proactive import record_user_message
from mirai.core.prompts.http_bridge import (
    format_effective_prompt_reply,
    http_delete_session_prompt,
    http_get_global_system_prompt,
    http_get_session_prompt,
    http_put_session_prompt,
)
from mirai.logging_config import get_logger
from mirai.telegram.bridge import chat_connection_config, save_token_for_telegram_user

# Pending tool confirmations: short_id -> Future[str] with values deny|allow|always
_PENDING_TOOL_CONFIRM: dict[str, asyncio.Future[str]] = {}

_MAX_MSG_LEN = 4096
_LOG = get_logger(__name__)


def _truncate_for_telegram(text: str, max_chars: int = 4090) -> str:
    """Telegram rejects ``send_message`` / ``reply_text`` when ``text`` length exceeds 4096."""
    s = text if isinstance(text, str) else str(text)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _api_url(connection: ConnectionConfig, path: str) -> str:
    if connection.mode == "relay":
        return f"{connection.base_url.rstrip('/')}/v1{path}"
    return f"{connection.base_url.rstrip('/')}{path}"


def _chat_url(connection: ConnectionConfig) -> str:
    if connection.mode == "relay":
        return f"{connection.base_url.rstrip('/')}/v1/chat"
    return f"{connection.base_url.rstrip('/')}/chat"


def _session_id_for_user(telegram_user_id: int) -> str:
    return f"tg_{telegram_user_id}"


def _split_telegram_text(text: str) -> list[str]:
    if len(text) <= _MAX_MSG_LEN:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        chunks.append(rest[:_MAX_MSG_LEN])
        rest = rest[_MAX_MSG_LEN:]
    return chunks


async def _send_long_text(send: Callable[[str], Awaitable[Any]], text: str) -> None:
    for chunk in _split_telegram_text(text):
        await send(chunk)


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


async def _put_chat_debug(
    connection: ConnectionConfig, session_id: str, enabled: bool
) -> tuple[bool, str, dict | None]:
    url = _api_url(connection, "/config/chat-debug")
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.put(url, json={"session_id": session_id, "enabled": enabled}, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500], None
        try:
            return True, "", r.json()
        except Exception:
            return True, "", None


async def _post_stt_transcribe(
    connection: ConnectionConfig,
    *,
    session_id: str,
    filename: str,
    data: bytes,
) -> tuple[bool, str]:
    url = _api_url(connection, "/stt/transcribe")
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"
    payload = {
        "session_id": session_id,
        "filename": filename,
        "content_base64": base64.standard_b64encode(data).decode("ascii"),
    }
    timeout = httpx.Timeout(10.0, read=600.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500]
        body = r.json()
        return True, str(body.get("text") or "").strip()


async def _get_model_config(connection: ConnectionConfig) -> dict[str, Any] | None:
    url = _api_url(connection, "/config/model")
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers)
        if r.status_code >= 400:
            return None
        return r.json()


def _authorized(user_id: int | None) -> bool:
    if user_id is None:
        return False
    allowed = get_telegram_allowed_user_ids()
    if not allowed:
        return True
    return user_id in allowed


def build_application():
    """Build and return python-telegram-bot Application (v21+)."""
    try:
        from telegram.constants import ChatAction
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    except ImportError as exc:
        raise RuntimeError(
            "Failed to import python-telegram-bot. Reinstall mirai-agent or run: pip install python-telegram-bot"
        ) from exc

    token = get_telegram_bot_token()
    if not token:
        raise RuntimeError(
            "Telegram bot token not set. Set TELEGRAM_BOT_TOKEN or add telegram_bot_token to ~/.mirai/config.json"
        )

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        await update.message.reply_text(
            "Mirai Telegram bridge.\n\n"
            "Send a message to chat. You can attach photos, files, or voice/audio when STT is enabled.\n"
            "For one message: add a caption to the photo, or send text in a separate message.\n"
            "Commands:\n"
            "/clear — clear this chat's history\n"
            "/model — show server model config\n"
            "/system — view or change this chat's system prompt (not global)\n"
            "/link — bind this Telegram account to your Mirai user (multi-tenant)\n"
            "/start_log — write full chat traces to ~/.mirai/debug/chat_trace/ (this session)\n"
            "/end_log — stop chat tracing\n"
            "/help — this message"
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await start_cmd(update, context)

    async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        uid = update.effective_user.id
        session_id = _session_id_for_user(uid)
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        ok, err = await _post_clear_session(connection, session_id)
        if ok:
            await update.message.reply_text("Session cleared.")
        else:
            await update.message.reply_text(_truncate_for_telegram(f"Failed to clear: {err}"))

    async def start_log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        uid = update.effective_user.id
        session_id = _session_id_for_user(uid)
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        ok, err, data = await _put_chat_debug(connection, session_id, True)
        if not ok:
            await update.message.reply_text(_truncate_for_telegram(f"Failed to start debug log: {err}"))
            return
        path = (data or {}).get("trace_path") or ""
        await update.message.reply_text(
            _truncate_for_telegram(
                "Chat debug logging ON for this session.\n"
                f"Trace file: {path}\n"
                "Logs include turn boundaries, each full LLM request (messages + tools), and stream events.\n"
                "Optional: set MIRAI_CHAT_DEBUG_REDACT_IMAGE_DATA=1 on the server to shorten inline data-URL images in the trace file only.\n"
                "Send /end_log to stop."
            )
        )

    async def end_log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        uid = update.effective_user.id
        session_id = _session_id_for_user(uid)
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        ok, err, data = await _put_chat_debug(connection, session_id, False)
        if not ok:
            await update.message.reply_text(_truncate_for_telegram(f"Failed to end debug log: {err}"))
            return
        path = (data or {}).get("trace_path") or ""
        if path:
            await update.message.reply_text(_truncate_for_telegram(f"Chat debug logging OFF. Last trace file:\n{path}"))
        else:
            await update.message.reply_text("Chat debug logging was not active for this session.")

    async def link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        if not context.args or not str(context.args[0]).strip():
            await update.message.reply_text(
                "Usage: /link <mirai_... access token>\n"
                "On mirai-enterprise, run: mirai-enterprise user-token <your_user_id> to get a token.\n"
                "In multi-tenant mode you must link before the API can act as your user."
            )
            return
        token = str(context.args[0]).strip()
        base = os.getenv("MIRAI_SERVER_URL", DEFAULT_LOCAL_SERVER_URL).rstrip("/")
        url = f"{base}/telegram/link"
        tg_uid = update.effective_user.id if update.effective_user else 0
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"telegram_user_id": int(tg_uid)},
                )
        except Exception as exc:
            await update.message.reply_text(_truncate_for_telegram(f"Link request failed: {exc}"))
            return
        if r.status_code >= 400:
            await update.message.reply_text(_truncate_for_telegram(f"Link failed ({r.status_code}): {r.text[:500]}"))
            return
        save_token_for_telegram_user(int(tg_uid), token)
        await update.message.reply_text(
            "Linked successfully. You can chat as usual (multi-tenant mode uses your Mirai user identity)."
        )

    async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        cfg = await _get_model_config(connection)
        if not cfg:
            await update.message.reply_text("Could not read /config/model from the server.")
            return
        lines = [
            f"Chat: {cfg.get('chat_provider', '?')} / {cfg.get('chat_model', '?')}",
            f"Embedding: {cfg.get('embedding_provider', '?')} / {cfg.get('embedding_model', '?')}",
        ]
        await update.message.reply_text("\n".join(lines))

    def _system_help_text() -> str:
        return (
            "/system — Session system prompt (Telegram session only; does not change global)\n\n"
            "/system — or /system show — show the effective prompt\n"
            "/system set <text> — set a session override\n"
            "/system reset — clear override; use server global default\n"
            "/system help — this help\n\n"
            "Multi-tenant: run /link first. Long prompts can be set via web UI or API."
        )

    async def system_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        uid = update.effective_user.id if update.effective_user else 0
        session_id = _session_id_for_user(uid)
        connection = chat_connection_config(uid)
        args = list(context.args or [])

        async def _do_show() -> None:
            sp, err = await http_get_session_prompt(connection, session_id)
            if err:
                hint = (
                    f"Auth required: multi-tenant users run /link <mirai_token> first. Detail: {err[:180]}"
                    if ("401" in err or "403" in err)
                    else err
                )
                await update.message.reply_text(_truncate_for_telegram(hint))
                return
            gp, err2 = await http_get_global_system_prompt(connection)
            if err2:
                await update.message.reply_text(_truncate_for_telegram(err2))
                return
            if sp.get("is_custom") and sp.get("system_prompt"):
                effective = str(sp["system_prompt"])
                label = "Session override"
            else:
                effective = str(gp.get("system_prompt") or "")
                label = "Global default"
            text = format_effective_prompt_reply(effective=effective, source_label=label)
            await _send_long_text(lambda t: update.message.reply_text(t), text)

        if not args or (len(args) == 1 and args[0].lower() in ("show", "get")):
            await _do_show()
            return
        if args[0].lower() in ("help", "?"):
            await update.message.reply_text(_system_help_text())
            return
        if args[0].lower() == "reset":
            ok, err = await http_delete_session_prompt(connection, session_id)
            if ok:
                await update.message.reply_text("Session override cleared; using the global system prompt.")
            else:
                await update.message.reply_text(_truncate_for_telegram(f"Failed: {err}"))
            return
        if args[0].lower() == "set":
            rest = " ".join(args[1:]).strip()
            if not rest:
                await update.message.reply_text("Usage: /system set <prompt text>")
                return
            ok, err = await http_put_session_prompt(connection, session_id, rest)
            if ok:
                await update.message.reply_text("Session system prompt updated.")
            else:
                await update.message.reply_text(_truncate_for_telegram(f"Failed: {err}"))
            return
        await update.message.reply_text("Unknown subcommand. Send /system help for usage.")

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Must answer the callback quickly; unblock the Future so /chat can continue.

        With default sequential updates, the message handler would still be awaiting the
        HTTP stream + confirmation Future—callback updates never run (deadlock). The app
        is built with ``concurrent_updates(True)`` so this handler runs in parallel.
        """
        query = update.callback_query
        if not query or not query.data:
            return
        data = query.data
        if not data.startswith("tc|"):
            return
        parts = data.split("|")
        if len(parts) != 3:
            await query.answer()
            return
        _, short_id, action = parts
        if action not in ("deny", "allow", "always"):
            await query.answer()
            return
        fut = _PENDING_TOOL_CONFIRM.pop(short_id, None)
        if fut is None or fut.done():
            await query.answer("Confirmation expired or already used.", show_alert=True)
            return
        await query.answer()
        fut.set_result(action)

    async def _append_saved_paths_from_telegram_media(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session_id: str,
        parts: list[str],
    ) -> bool:
        """Download photo / document into ``~/.mirai/uploads/<session_id>/`` and append paths.

        Returns False if a fatal error was already reported to the user (stop processing).
        """
        msg = update.message
        if not msg:
            return True

        if msg.photo:
            photo = msg.photo[-1]
            file_id = photo.file_id
            try:
                tg_file = await context.bot.get_file(file_id)
                data = await tg_file.download_as_bytearray()
            except Exception as exc:
                await msg.reply_text(_truncate_for_telegram(f"Could not download image from Telegram: {exc}"))
                return False
            if len(data) > MAX_UPLOAD_BYTES:
                await msg.reply_text(f"Image too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
                return False
            name = f"telegram_photo_{photo.file_unique_id}.jpg"
            try:
                res = save_uploaded_file(session_id, name, bytes(data))
            except HTTPException as exc:
                await msg.reply_text(_truncate_for_telegram(f"Could not save image: {exc.detail}"))
                return False
            parts.append(res["path"])

        if msg.document:
            doc = msg.document
            if doc.file_size and doc.file_size > MAX_UPLOAD_BYTES:
                await msg.reply_text(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
                return False
            try:
                tg_file = await context.bot.get_file(doc.file_id)
                data = await tg_file.download_as_bytearray()
            except Exception as exc:
                await msg.reply_text(_truncate_for_telegram(f"Could not download file from Telegram: {exc}"))
                return False
            if len(data) > MAX_UPLOAD_BYTES:
                await msg.reply_text(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
                return False
            name = doc.file_name or f"telegram_doc_{doc.file_unique_id}"
            try:
                res = save_uploaded_file(session_id, name, bytes(data))
            except HTTPException as exc:
                await msg.reply_text(_truncate_for_telegram(f"Could not save file: {exc.detail}"))
                return False
            parts.append(res["path"])

        return True

    async def _append_transcribed_telegram_audio(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        connection: ConnectionConfig,
        session_id: str,
        parts: list[str],
    ) -> bool:
        msg = update.message
        if not msg:
            return True
        voice = msg.voice
        audio = msg.audio
        if not voice and not audio:
            return True
        media = voice or audio
        audio_bytes = getattr(media, "file_size", None)
        if audio_bytes is not None and audio_bytes > MAX_UPLOAD_BYTES:
            await msg.reply_text(f"Audio too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
            return False
        try:
            tg_file = await context.bot.get_file(media.file_id)
            data = await tg_file.download_as_bytearray()
        except Exception as exc:
            await msg.reply_text(_truncate_for_telegram(f"Could not download audio from Telegram: {exc}"))
            return False
        if len(data) > MAX_UPLOAD_BYTES:
            await msg.reply_text(f"Audio too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
            return False
        if audio and audio.file_name:
            filename = audio.file_name
        else:
            filename = f"telegram_voice_{media.file_unique_id}.ogg"
        ok, text = await _post_stt_transcribe(connection, session_id=session_id, filename=filename, data=bytes(data))
        if not ok:
            await msg.reply_text(_truncate_for_telegram(f"Voice transcription failed: {text}"))
            return False
        if not text:
            await msg.reply_text("Voice transcription did not produce any text.")
            return False
        parts.append(text)
        return True

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        session_id = _session_id_for_user(user_id)
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)

        parts: list[str] = []
        caption_or_text = (update.message.text or update.message.caption or "").strip()
        if caption_or_text:
            parts.append(caption_or_text)

        if update.message.voice or update.message.audio:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            ok = await _append_transcribed_telegram_audio(update, context, connection, session_id, parts)
            if not ok:
                return

        if update.message.photo or update.message.document:
            ok = await _append_saved_paths_from_telegram_media(update, context, session_id, parts)
            if not ok:
                return

        if not parts:
            return

        prompt = "\n".join(parts)
        record_user_message(session_id)

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        url = _chat_url(connection)
        headers = connection.auth_headers()
        headers["Content-Type"] = "application/json"
        payload = {"prompt": prompt, "session_id": session_id}
        timeout = httpx.Timeout(10.0, read=600.0)

        accumulated: list[str] = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    await update.message.reply_text(
                        _truncate_for_telegram(f"HTTP {response.status_code}: {body[:500]}")
                    )
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
                        et = event.get("type")
                        if et == "text":
                            accumulated.append(str(event.get("content", "")))
                        elif et == "tool_confirmation":
                            call_id = str(event.get("call_id", ""))
                            tool_name = str(event.get("tool_name", ""))
                            args = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
                            short_id = uuid.uuid4().hex
                            fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
                            _PENDING_TOOL_CONFIRM[short_id] = fut
                            args_preview = json.dumps(args, ensure_ascii=False)[:800]
                            text = _truncate_for_telegram(
                                f"Tool confirmation required\n\nTool: {tool_name}\nArguments: {args_preview}"
                            )
                            keyboard = InlineKeyboardMarkup(
                                [
                                    [
                                        InlineKeyboardButton("Deny", callback_data=f"tc|{short_id}|deny"),
                                        InlineKeyboardButton("Allow", callback_data=f"tc|{short_id}|allow"),
                                    ],
                                    [
                                        InlineKeyboardButton("Always allow", callback_data=f"tc|{short_id}|always"),
                                    ],
                                ]
                            )
                            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)

                            try:
                                action = await asyncio.wait_for(fut, timeout=600.0)
                            except asyncio.TimeoutError:
                                await context.bot.send_message(chat_id=chat_id, text="Confirmation timed out.")
                                action = "deny"
                            finally:
                                _PENDING_TOOL_CONFIRM.pop(short_id, None)

                            decision_map = {"deny": "deny", "allow": "allow", "always": "always_allow"}
                            dkey = decision_map.get(action, "deny")
                            ok, err = await _post_tool_confirm(connection, call_id, dkey)
                            if not ok:
                                await context.bot.send_message(
                                    chat_id=chat_id,
                                    text=_truncate_for_telegram(f"Confirm failed: {err}"),
                                )
                        elif et == "error":
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=_truncate_for_telegram(f"Error: {event.get('content', 'Unknown')}"),
                            )

        if accumulated:
            await _send_long_text(lambda t: update.message.reply_text(t), "".join(accumulated))

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        _LOG.exception("Telegram handler error", exc_info=context.error)
        if update is not None and getattr(update, "effective_message", None):
            try:
                await update.effective_message.reply_text(
                    _truncate_for_telegram("Something went wrong. Please try again or check server logs.")
                )
            except Exception:
                pass

    app = Application.builder().token(token).concurrent_updates(True).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("start_log", start_log_cmd))
    app.add_handler(CommandHandler("end_log", end_log_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler("system", system_cmd))
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^tc\|"))
    # Text, photos, and documents (files). Images are inlined for vision-capable chat models;
    # other paths are read via the server `read_file` tool when needed.
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VOICE | filters.AUDIO) & ~filters.COMMAND,
            on_message,
        )
    )

    return app


def run_telegram_bot_sync() -> None:
    """Entry point: run polling until Ctrl+C."""
    app = build_application()
    app.run_polling(close_loop=False)
