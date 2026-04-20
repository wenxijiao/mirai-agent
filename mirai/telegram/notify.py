"""Server-side Telegram outbound: timer completions without a /timer-events client."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from mirai.core.config import get_telegram_bot_token

logger = logging.getLogger(__name__)

_TG_SESSION = re.compile(r"^tg_(\d+)$")
_MAX_MESSAGE = 4096


def parse_telegram_chat_id(session_id: str) -> int | None:
    """Map Mirai session ``tg_<user_id>`` to Telegram private chat_id."""
    m = _TG_SESSION.match(session_id.strip())
    if not m:
        return None
    return int(m.group(1))


def _events_to_plain_text(events: list[dict[str, Any]]) -> str:
    return "".join(str(e.get("content", "")) for e in events if e.get("type") == "text").strip()


def _chunk_message(text: str) -> list[str]:
    if not text:
        return []
    if len(text) <= _MAX_MESSAGE:
        return [text]
    out: list[str] = []
    rest = text
    while rest:
        out.append(rest[:_MAX_MESSAGE])
        rest = rest[_MAX_MESSAGE:]
    return out


async def send_timer_result_to_telegram(
    session_id: str,
    description: str,
    events: list[dict[str, Any]],
) -> None:
    """If session is ``tg_*`` and bot token is set, POST sendMessage to Telegram API."""
    chat_id = parse_telegram_chat_id(session_id)
    if chat_id is None:
        return

    token = get_telegram_bot_token()
    if not token:
        logger.info(
            "Telegram timer notify skipped: no bot token in this API process. "
            "On the machine running `mirai --server`, set TELEGRAM_BOT_TOKEN or "
            "telegram_bot_token in ~/.mirai/config.json (same machine as the API)."
        )
        return

    body = _events_to_plain_text(events)
    if not body:
        errs = [str(e.get("content", "")) for e in events if e.get("type") == "error"]
        if errs:
            body = "Error: " + errs[0]
        else:
            body = f"[Timer] {description}"

    text = "⏰ " + body
    chunks = _chunk_message(text)
    if not chunks:
        chunks = ["⏰ Timer completed."]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for part in chunks:
            try:
                r = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": part,
                        "disable_web_page_preview": True,
                    },
                )
                if r.status_code >= 400:
                    logger.warning(
                        "Telegram sendMessage HTTP %s: %s",
                        r.status_code,
                        r.text[:400],
                    )
                    continue
                try:
                    payload = r.json()
                except Exception:
                    payload = {}
                if payload.get("ok") is True:
                    logger.info("Telegram timer message sent to chat_id=%s", chat_id)
                else:
                    logger.warning(
                        "Telegram sendMessage rejected: %s",
                        payload.get("description") or r.text[:400],
                    )
            except Exception as exc:
                logger.warning("Telegram sendMessage error: %s", exc)
