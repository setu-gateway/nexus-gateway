import contextvars
from datetime import datetime, timezone
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def set_trace_id(trace_id: str) -> None:
    """Set trace_id in current execution context."""
    trace_id_ctx.set(trace_id)


def set_request_id(request_id: str) -> None:
    """Set request_id in current execution context."""
    request_id_ctx.set(request_id)


def get_trace_id() -> str:
    """Get trace_id from current execution context."""
    return trace_id_ctx.get()


def get_request_id() -> str:
    """Get request_id from current execution context."""
    return request_id_ctx.get()


def clear_context() -> None:
    """Clear tracing context variables."""
    trace_id_ctx.set("")
    request_id_ctx.set("")


class JSONFormatter(logging.Formatter):
    """Custom logging formatter that outputs logs strictly as structured JSON objects."""

    def __init__(self, service_name: Optional[str] = None):
        super().__init__()
        self.service_name = service_name or os.getenv("SERVICE_NAME", "gateway")

    def format(self, record: logging.LogRecord) -> str:
        log_object: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", None) or get_trace_id(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
            "service": getattr(record, "service", None) or self.service_name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_object["exception"] = self.formatException(record.exc_info)

        reserved_keys = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "trace_id", "request_id", "service"
        }
        for key, value in record.__dict__.items():
            if key not in reserved_keys:
                log_object[key] = value

        return json.dumps(log_object, default=str)


def setup_structured_logging(
    service_name: str = "gateway",
    level: str = "INFO",
) -> logging.Logger:
    """Configure root logger to enforce structured JSON output."""
    log_level = getattr(logging, os.getenv("LOG_LEVEL", level).upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(JSONFormatter(service_name=service_name))

    root_logger.addHandler(handler)
    return logging.getLogger(service_name)


def get_logger(name: str = "gateway") -> logging.Logger:
    """Get a structured logger instance."""
    return logging.getLogger(name)
