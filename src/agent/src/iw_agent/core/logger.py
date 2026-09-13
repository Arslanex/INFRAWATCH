from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import queue
import sys
from datetime import datetime, timezone
from pathlib import Path

LOGGER_NAME = "iw_agent"
LOG_DIR = Path("logs")
ERROR_LOG_FILE = LOG_DIR / "error.log"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

_listener: logging.handlers.QueueListener | None = None


class ErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name,
            "pathname": record.pathname,
            "lineno": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _console_handler() -> logging.StreamHandler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    return handler


def _rotating_file_handler() -> logging.handlers.RotatingFileHandler:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.ERROR)
    handler.addFilter(ErrorFilter())
    handler.setFormatter(JsonFormatter())
    return handler


def _setup_logger() -> logging.Logger:
    global _listener

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        return logger

    console_handler = _console_handler()

    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setLevel(logging.ERROR)
    queue_handler.addFilter(ErrorFilter())

    file_handler = _rotating_file_handler()
    _listener = logging.handlers.QueueListener(
        log_queue,
        file_handler,
        respect_handler_level=True,
    )
    _listener.start()
    atexit.register(_listener.stop)

    logger.addHandler(console_handler)
    logger.addHandler(queue_handler)
    return logger


logger = _setup_logger()


def configure_cli_logging() -> None:
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            handler.setLevel(logging.WARNING)
