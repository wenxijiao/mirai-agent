"""Backward-compatible imports for the versioned prompt catalog.

New model-facing copy belongs in :mod:`yumi.core.features.prompts.catalog`.
This module remains so existing integrations importing ``prompts.defaults`` do
not break.
"""

from yumi.core.features.prompts.catalog import (
    CHAT_PROMPT_CATALOG_HASH,
    CHAT_PROMPT_VERSION,
    DEFAULT_SYSTEM_PROMPT,
    NO_VISION_IMAGE_UPLOAD_INSTRUCTION,
    UPLOAD_FILE_INSTRUCTION,
    build_tool_use_instruction,
    prompt_catalog_metadata,
)

__all__ = [
    "CHAT_PROMPT_CATALOG_HASH",
    "CHAT_PROMPT_VERSION",
    "DEFAULT_SYSTEM_PROMPT",
    "NO_VISION_IMAGE_UPLOAD_INSTRUCTION",
    "UPLOAD_FILE_INSTRUCTION",
    "build_tool_use_instruction",
    "prompt_catalog_metadata",
]
