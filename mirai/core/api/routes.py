"""Compatibility alias for the Mirai FastAPI app module.

Historically ``mirai.core.api.routes`` contained the whole application. The
implementation now lives in ``app_factory``, but this module remains a true
alias so existing imports and monkeypatch-based tests keep targeting the same
objects.
"""

import sys

from mirai.core.api import app_factory as _app_factory

sys.modules[__name__] = _app_factory
