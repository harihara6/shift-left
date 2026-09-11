"""Logging setup and the per-request access log.

Every request gets an id - taken from `X-Request-ID` when a proxy already assigned one, minted
otherwise - that is echoed back on the response and stamped on each log line, so a user's
report and the service's logs can be matched.

Headers are never logged. They carry identity and, behind the SSO proxy, the proxy secret.
"""

import json
import logging
import logging.config
import re
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings

request_id: ContextVar[str] = ContextVar("request_id", default="-")

# A caller-supplied id is echoed into logs and responses, so it is held to a safe shape.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

access_logger = logging.getLogger("shiftleft.access")
error_logger = logging.getLogger("shiftleft.errors")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


def configure_logging(settings: Settings) -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
    formatter: dict = {"format": fmt}
    if settings.log_json:
        formatter = {"()": "pythonjsonlogger.json.JsonFormatter", "format": fmt}
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": _RequestIdFilter}},
            "formatters": {"default": formatter},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                }
            },
            "loggers": {
                "shiftleft": {"handlers": ["stdout"], "level": settings.log_level, "propagate": False},
                # This middleware writes the access log, so uvicorn's own would be a duplicate.
                "uvicorn.access": {"level": "WARNING"},
            },
        }
    )


class RequestContextMiddleware:
    """Assigns the request id and writes one access-log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = request_id.set(rid)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_started = True
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # The traceback goes to the log; the caller gets the request id and nothing else.
            error_logger.exception("Unhandled error on %s %s", scope["method"], scope["path"])
            if response_started:
                raise
            body = json.dumps({"detail": "Internal error", "request_id": rid}).encode()
            await send_with_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            access_logger.info(
                "%s %s %s %.1fms",
                scope["method"],
                scope["path"],
                status_code,
                (time.perf_counter() - started) * 1000,
            )
            request_id.reset(token)
