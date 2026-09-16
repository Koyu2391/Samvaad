"""
Phase 5: JSON access/error logging + request IDs (stdlib only).

- configure_logging(): JSON formatter on all root handlers (uvicorn included).
- request_id_ctx: contextvar carrying the current request ID.
- RequestIDMiddleware: sets/propagates X-Request-ID, logs method/path/status/ms.
"""
import json
import logging
import time
import uuid
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc"] = self.formatException(record.exc_info)[:2000]
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Quiet noisy libs; our JSON still captures warnings+.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def request_id_middleware(request, call_next):
    from starlette.responses import Response as StarletteResponse

    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request_id_ctx.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logging.getLogger("samvaad.access").exception(
            "unhandled %s %s", request.method, request.url.path
        )
        raise
    ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = rid
    # Skip health/readiness noise at INFO; keep them at DEBUG.
    logger = logging.getLogger("samvaad.access")
    if request.url.path in ("/api/health", "/api/ready"):
        logger.debug("%s %s %s %.1fms", request.method, request.url.path,
                     response.status_code, ms)
    else:
        logger.info("%s %s %s %.1fms", request.method, request.url.path,
                    response.status_code, ms)
    if isinstance(response, StarletteResponse) and response.status_code >= 500:
        from core.metrics import incr

        incr("http_5xx")
    return response
