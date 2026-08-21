"""
Shared ASGI middleware for engine APIs.

CorrelationIDMiddleware — honours an inbound X-Correlation-ID (or generates
one), binds it to the log context, and echoes it on the response so a request
can be traced across engines.

RequestLoggingMiddleware — one structured line per request with method, path,
status and duration.
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from .logger import LogContext, setup_logger

CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        correlation_id = request.headers.get(CORRELATION_HEADER) or uuid.uuid4().hex[:16]
        request.state.correlation_id = correlation_id
        with LogContext(correlation_id=correlation_id):
            response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, engine_name: str = "engine"):
        super().__init__(app)
        self.logger = setup_logger(f"{engine_name}.requests", engine_name=engine_name)

    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        self.logger.info(
            "%s %s",
            request.method,
            request.url.path,
            extra={
                "extra_fields": {
                    "status": response.status_code,
                    "duration_ms": round((time.time() - start) * 1000, 2),
                }
            },
        )
        return response
