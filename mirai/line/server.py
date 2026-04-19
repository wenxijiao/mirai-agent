"""Standalone LINE webhook server (topology B: sidecar to core Mirai HTTP API)."""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI, Request, Response

from mirai.core.config.line import get_line_bot_port, get_line_channel_secret
from mirai.logging_config import configure_logging, get_logger

_LOG = get_logger(__name__)


def build_line_app() -> FastAPI:
    app = FastAPI(title="Mirai LINE webhook")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "mirai-line-webhook"}

    @app.post("/line/webhook")
    async def line_webhook(request: Request) -> Response:
        if not get_line_channel_secret():
            return Response(status_code=503, content="LINE not configured")
        body = await request.body()
        sig = request.headers.get("X-Line-Signature")
        from mirai.line.handlers import dispatch_line_webhook

        try:
            await dispatch_line_webhook(body, sig, use_http=True)
        except PermissionError:
            return Response(status_code=401, content="invalid signature")
        except ValueError as exc:
            return Response(status_code=400, content=str(exc)[:500])
        except RuntimeError as exc:
            return Response(status_code=503, content=str(exc)[:500])
        return Response(status_code=200)

    return app


def run_line_bot_sync() -> None:
    configure_logging()
    port = get_line_bot_port()
    host = os.getenv("LINE_BOT_HOST", "0.0.0.0").strip() or "0.0.0.0"
    app = build_line_app()
    _LOG.info("Starting LINE webhook on %s:%s (set webhook URL to http(s)://<host>:%s/line/webhook)", host, port, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
