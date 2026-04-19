"""Allow ``python -m mirai.core.api`` to start the server."""

import logging

import uvicorn
from mirai.core.api.routes import app

logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False, log_level="warning")
