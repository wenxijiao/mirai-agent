"""Load optional dotenv files so ``MIRAI_*``, ``HF_*``, etc. apply without manual export."""

from __future__ import annotations

from pathlib import Path


def load_mirai_dotenv() -> None:
    """Load ``~/.mirai/.env`` then ``./.env``; never override existing OS environment."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    from mirai.core.config.paths import CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    load_dotenv(CONFIG_DIR / ".env", override=False)
    load_dotenv(Path.cwd() / ".env", override=False)
