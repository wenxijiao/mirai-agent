"""Load/save ModelConfig JSON with environment-variable overrides."""

import json
import os

from mirai.core.config.model import ModelConfig
from mirai.core.config.paths import CONFIG_PATH, ensure_config_dir


def load_saved_model_config() -> ModelConfig:
    if not CONFIG_PATH.exists():
        return ModelConfig()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ModelConfig()

    try:
        return ModelConfig.model_validate(data)
    except Exception:
        return ModelConfig()


def load_model_config() -> ModelConfig:
    config = load_saved_model_config()

    chat_provider = os.getenv("MIRAI_CHAT_PROVIDER")
    chat_model = os.getenv("MIRAI_CHAT_MODEL")
    embedding_provider = os.getenv("MIRAI_EMBEDDING_PROVIDER")
    embedding_model = os.getenv("MIRAI_EMBED_MODEL")

    if chat_provider:
        config.chat_provider = chat_provider.strip()
    if chat_model:
        config.chat_model = chat_model.strip()
    if embedding_provider:
        config.embedding_provider = embedding_provider.strip()
    if embedding_model:
        config.embedding_model = embedding_model.strip()

    mem_recent = os.getenv("MIRAI_MEMORY_MAX_RECENT")
    if mem_recent:
        try:
            config.memory_max_recent_messages = max(
                1,
                min(500, int(mem_recent.strip())),
            )
        except ValueError:
            pass
    mem_related = os.getenv("MIRAI_MEMORY_MAX_RELATED")
    if mem_related:
        try:
            config.memory_max_related_messages = max(
                0,
                min(100, int(mem_related.strip())),
            )
        except ValueError:
            pass

    def _env_bool(name: str, current: bool) -> bool:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return current
        v = str(raw).strip().lower()
        if v in ("0", "false", "no", "off"):
            return False
        if v in ("1", "true", "yes", "on"):
            return True
        return current

    config.chat_append_current_time = _env_bool("MIRAI_CHAT_APPEND_CURRENT_TIME", config.chat_append_current_time)
    config.chat_append_tool_use_instruction = _env_bool(
        "MIRAI_CHAT_APPEND_TOOL_INSTRUCTION", config.chat_append_tool_use_instruction
    )
    config.edge_tools_enable_dynamic_routing = _env_bool(
        "MIRAI_EDGE_TOOLS_DYNAMIC_ROUTING", config.edge_tools_enable_dynamic_routing
    )

    edge_limit = os.getenv("MIRAI_EDGE_TOOLS_RETRIEVAL_LIMIT")
    if edge_limit:
        try:
            config.edge_tools_retrieval_limit = max(0, min(200, int(edge_limit.strip())))
        except ValueError:
            pass

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if tg_token and tg_token.strip():
        config.telegram_bot_token = tg_token.strip()

    tg_allow = os.getenv("TELEGRAM_ALLOWED_USER_IDS")
    if tg_allow and tg_allow.strip():
        ids: list[int] = []
        for part in tg_allow.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                pass
        if ids:
            config.telegram_allowed_user_ids = ids

    line_secret = os.getenv("LINE_CHANNEL_SECRET")
    if line_secret and line_secret.strip():
        config.line_channel_secret = line_secret.strip()
    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if line_token and line_token.strip():
        config.line_channel_access_token = line_token.strip()
    line_allow = os.getenv("LINE_ALLOWED_USER_IDS")
    if line_allow and line_allow.strip():
        lids = [p.strip() for p in line_allow.split(",") if p.strip()]
        if lids:
            config.line_allowed_user_ids = lids
    line_port = os.getenv("LINE_BOT_PORT")
    if line_port and line_port.strip():
        try:
            config.line_bot_port = max(1, min(65535, int(line_port.strip())))
        except ValueError:
            pass

    return config


def save_model_config(config: ModelConfig) -> None:
    ensure_config_dir()
    CONFIG_PATH.write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
