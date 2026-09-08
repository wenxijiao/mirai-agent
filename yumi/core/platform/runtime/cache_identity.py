"""Stable, opaque cache identity shared by every channel of one account."""

import hashlib

from yumi.core.platform.plugins import get_current_identity
from yumi.core.platform.runtime.caller_context import get_chat_owner_user_id
from yumi.core.platform.runtime.usage_context import usage_owner_id


def cache_owner() -> str:
    from yumi.core.platform.plugins import SINGLE_USER_ID

    owner = usage_owner_id.get() or get_chat_owner_user_id()
    return get_current_identity().user_id if owner == SINGLE_USER_ID else owner


def provider_cache_user_id() -> str:
    return "yumi_" + hashlib.sha256(("yumi-cache-v1\0" + cache_owner()).encode()).hexdigest()
