"""Optional in-core LINE webhook (``MIRAI_LINE_INCORE=1``)."""

from __future__ import annotations

from fastapi import FastAPI, Request, Response
from mirai.core.config.line import get_line_channel_secret


def try_register_line_webhook(app: FastAPI) -> None:
    """Register ``POST /line/webhook`` once when in-core LINE mode is enabled."""
    if getattr(app.state, "line_webhook_registered", False):
        return
    from mirai.core.config.line import line_incore_enabled

    if not line_incore_enabled() or not get_line_channel_secret():
        return
    app.state.line_webhook_registered = True

    @app.post("/line/webhook")
    async def line_webhook_incore(request: Request) -> Response:
        body = await request.body()
        sig = request.headers.get("X-Line-Signature")
        from mirai.line.handlers import dispatch_line_webhook

        try:
            await dispatch_line_webhook(body, sig, use_http=False)
        except PermissionError:
            return Response(status_code=401, content="invalid signature")
        except ValueError as exc:
            return Response(status_code=400, content=str(exc)[:500])
        except RuntimeError as exc:
            return Response(status_code=503, content=str(exc)[:500])
        return Response(status_code=200)
