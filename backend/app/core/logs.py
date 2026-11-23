"""Logging for the API and the worker: one line per event on stdout, which is where hosts
like Render collect logs from.

Every line carries the request or background job it belongs to, so the lines of one failing
request can be found together, and the reference an error message shows a person (its
request ID) leads straight to them. Readable text while developing; JSON in production, so a
log service can search by field (LOG_FORMAT changes either).
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

# set for the length of a request (app.core.requests) or a background job (app.services.jobs)
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
job: ContextVar[str | None] = ContextVar("job", default=None)

# attributes every LogRecord has; anything else on a record came from `extra=`
_STANDARD = set(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
    "color_message",  # uvicorn's copy of the message with terminal colours
}
_CONTEXT = ("request_id", "job")
# libraries that are chatty at INFO
_QUIET = ("httpx", "httpx2", "httpcore", "anthropic", "mcp", "sse_starlette", "urllib3")


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    if record.name.startswith("celery"):
        return {}  # Celery attaches its task data, which its message already says
    return {
        k: v
        for k, v in vars(record).items()
        if k not in _STANDARD and k not in _CONTEXT and not k.startswith("_")
    }


class ContextFilter(logging.Filter):
    """Adds the current request ID and job to records made before setup_logging()."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id.get()
            record.job = job.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _CONTEXT:
            if value := getattr(record, key, None):
                line[key] = value
        line.update(_extras(record))
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        tags = [f"{k}={getattr(record, k)}" for k in _CONTEXT if getattr(record, k, None)]
        tags += [f"{k}={v}" for k, v in _extras(record).items()]
        if not tags:
            return text
        first, _, rest = text.partition("\n")  # keep a traceback below the tags
        return f"{first}  [{' '.join(tags)}]" + (f"\n{rest}" if rest else "")


_make_record = logging.getLogRecordFactory()


def _record_with_context(*args: Any, **kwargs: Any) -> logging.LogRecord:
    # at creation, so every handler sees it (Sentry's and the tests' too, not just ours)
    record = _make_record(*args, **kwargs)
    record.request_id = request_id.get()
    record.job = job.get()
    return record


def setup_logging() -> None:
    """Send every logger's records to one stdout handler. Safe to call more than once."""
    logging.setLogRecordFactory(_record_with_context)
    root = logging.getLogger()
    # This owns the root logger. Libraries that set up logging themselves (the MCP SDK adds a
    # Rich handler on stderr) would otherwise print every line twice. pytest's capture stays.
    for handler in list(root.handlers):
        if not type(handler).__module__.startswith("_pytest"):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.dealflow = True  # type: ignore[attr-defined]
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else TextFormatter())
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)
    # uvicorn and Celery set up handlers of their own; route their records through ours
    for name in ("uvicorn", "uvicorn.error", "celery", "celery.task", "celery.worker"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # one line per request comes from app.core.requests instead, with its ID and timing
    logging.getLogger("uvicorn.access").disabled = True
    for name in _QUIET:
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))
