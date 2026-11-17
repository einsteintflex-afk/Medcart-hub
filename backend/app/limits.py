"""Request-body size limit as pure ASGI middleware (counts streamed bytes, so chunked uploads can't bypass it)."""
import json

from .config import get_settings


class BodyLimit:
    def __init__(self, app, json_limit: int = 1024 * 1024):
        self.app, self.json_limit = app, json_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS", "DELETE"):
            return await self.app(scope, receive, send)
        is_upload = scope["path"].endswith(("/files", "/ai/transcribe"))
        limit = (get_settings().max_upload_mb + 1) * 1024 * 1024 if is_upload else self.json_limit
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return await self._reject(send)
        seen = 0

        class TooLarge(Exception):
            pass

        async def counted():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise TooLarge
            return msg

        started = False

        async def tracking_send(msg):
            nonlocal started
            started = True
            await send(msg)

        try:
            await self.app(scope, counted, tracking_send)
        except TooLarge:
            if not started:
                await self._reject(send)

    @staticmethod
    async def _reject(send):
        body = json.dumps({"detail": "Request body too large"}).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
