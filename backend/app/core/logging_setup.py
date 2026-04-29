"""
Structured JSON logging.

Format:
  {"asctime": "...", "level": "INFO", "name": "app.api.v1.invoices",
   "message": "...", "request_id": "...", "user_id": 4}

Loggers configured:
  - root (default level WARNING)
  - app.* (INFO in dev, INFO in prod)
  - uvicorn.access — JSON-formatted access lines

Usage:
    from app.core.logging_setup import configure_logging, get_logger
    configure_logging()
    log = get_logger(__name__)
    log.info("issued invoice", extra={"invoice_id": 42, "user_id": user.id})
"""
from __future__ import annotations

import logging
import logging.config
import sys

# python-json-logger renamed the module in 3.x; the new module name works on
# both 3.x stable releases.
from pythonjsonlogger.json import JsonFormatter as _JsonBase

from app.core.config import settings


class _JsonFormatter(_JsonBase):
    """Adds an `app` field so multiple services can share a log pipeline."""

    def add_fields(self, log_record, record, message_dict):  # type: ignore[override]
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("app", "jewelry-erp")
        log_record.setdefault("env", settings.environment)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        _JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"levelname": "level", "asctime": "ts"},
        )
    )

    root = logging.getLogger()
    # Remove default handlers so we don't double-log under uvicorn.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    # App-namespaced logger gets INFO so business events show up.
    app_log = logging.getLogger("app")
    app_log.setLevel(level)
    app_log.propagate = True

    # Tame uvicorn's stdout — it sets up its own handlers.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(noisy)
        lg.handlers.clear()
        lg.addHandler(handler)
        lg.propagate = False
        lg.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
