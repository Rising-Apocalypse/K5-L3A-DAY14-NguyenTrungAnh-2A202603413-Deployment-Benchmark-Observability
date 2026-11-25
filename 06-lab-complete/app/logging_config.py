"""Structured logging — mỗi dòng log là một JSON object."""
import json
import logging
import sys
from datetime import datetime, timezone

from app.config import settings

# Thuộc tính có sẵn của LogRecord; phần còn lại là field truyền qua extra={...}
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName", "color_message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    # Log của uvicorn đi chung handler JSON; access log tắt vì middleware đã ghi mỗi request
    for name in ("uvicorn", "uvicorn.error"):
        log = logging.getLogger(name)
        log.handlers = []
        log.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
