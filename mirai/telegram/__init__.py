"""Telegram bridge for Mirai (dependencies bundled with mirai-agent)."""

from mirai.telegram.bot import build_application, run_telegram_bot_sync
from mirai.telegram.notify import send_timer_result_to_telegram

__all__ = ["build_application", "run_telegram_bot_sync", "send_timer_result_to_telegram"]
