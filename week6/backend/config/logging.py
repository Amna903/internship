"""Week 6 Step 6: JSON log lines carrying the current request id (O1, O2).

Fields are whitelisted: time, level, logger, message, request_id, plus the `extra` keys in FIELDS. Messages are
written by our code and never include question text, answers, bodies, query strings, emails or passwords.
"""

import contextvars
import json
import logging
from datetime import UTC, datetime

request_id = contextvars.ContextVar("request_id", default=None)

FIELDS = ("method", "route", "status", "duration_ms", "user_id", "job_id", "event")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        line = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
        }
        line.update({k: getattr(record, k) for k in FIELDS if hasattr(record, k)})
        if record.exc_info:
            line["error"] = record.exc_info[0].__name__  # the class only: messages can hold SQL or values
        return json.dumps(line, default=str)
