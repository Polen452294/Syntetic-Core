"""Context propagation across ASGI requests, task threads and browser IPC."""

from contextvars import ContextVar
from uuid import UUID, uuid4

trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
log_context: ContextVar[dict | None] = ContextVar("log_context", default=None)
log_spool: ContextVar[str | None] = ContextVar("log_spool", default=None)


def normalize_trace(value: str | None) -> str:
    try:
        parsed = UUID(value or "")
        if parsed.version == 4:
            return str(parsed)
    except (ValueError, TypeError, AttributeError):
        pass
    return str(uuid4())
