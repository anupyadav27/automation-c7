"""
Shared structured logging for all engines.

`setup_logger` returns a stdlib logger with a consistent format that includes
the engine name; `LogContext` binds request-scoped fields (tenant_id,
correlation_id, …) via contextvars so log lines inside the block carry them;
`log_duration` emits a uniform timing line.

Kept dependency-free: stdlib only, so every engine (Lambda, K8s Job, CLI)
can import it.
"""
import contextvars
import logging
import sys

_log_context: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "log_context", default={}
)

_FORMAT = "%(asctime)s %(levelname)-8s %(engine)s %(name)s — %(message)s%(context_suffix)s"


class _ContextFilter(logging.Filter):
    """Injects engine name and bound LogContext fields into every record."""

    def __init__(self, engine_name: str):
        super().__init__()
        self.engine_name = engine_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.engine = self.engine_name
        ctx = _log_context.get()
        extra_fields = getattr(record, "extra_fields", None)
        merged = {**ctx, **(extra_fields or {})}
        record.context_suffix = (
            " | " + " ".join(f"{k}={v}" for k, v in merged.items()) if merged else ""
        )
        return True


def setup_logger(name: str, engine_name: str = "engine") -> logging.Logger:
    """Return a configured logger; safe to call more than once per module."""
    logger = logging.getLogger(name)
    if not any(isinstance(f, _ContextFilter) for f in logger.filters):
        logger.addFilter(_ContextFilter(engine_name))
    if not logger.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class LogContext:
    """Bind fields to every log line emitted inside the block.

    with LogContext(tenant_id=tenant_id):
        logger.info("assets listed")   # → … | tenant_id=t1
    """

    def __init__(self, **fields):
        self.fields = {k: v for k, v in fields.items() if v is not None}
        self._token = None

    def __enter__(self):
        current = _log_context.get()
        self._token = _log_context.set({**current, **self.fields})
        return self

    def __exit__(self, *exc):
        if self._token is not None:
            _log_context.reset(self._token)
        return False


def log_duration(logger: logging.Logger, message: str, duration_ms: float) -> None:
    """Uniform timing line so dashboards can parse duration_ms."""
    logger.info("%s", message, extra={"extra_fields": {"duration_ms": round(duration_ms, 2)}})
