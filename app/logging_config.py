"""JSON-structured logging with request IDs."""

import logging
import sys
import time
import uuid
from contextvars import ContextVar

import structlog

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def add_request_id(_logger, _name, event_dict):
    event_dict["request_id"] = request_id_var.get()
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_request_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


def get_logger(name: str = "app"):
    return structlog.get_logger(name)


class TimedOperation:
    """Context manager that logs how long a block took."""

    def __init__(self, logger, name: str, **kwargs):
        self.logger = logger
        self.name = name
        self.kwargs = kwargs

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        duration_ms = (time.perf_counter() - self.start) * 1000
        if exc:
            self.logger.error(
                self.name, duration_ms=round(duration_ms, 2), error=str(exc), **self.kwargs
            )
        else:
            self.logger.info(self.name, duration_ms=round(duration_ms, 2), **self.kwargs)
