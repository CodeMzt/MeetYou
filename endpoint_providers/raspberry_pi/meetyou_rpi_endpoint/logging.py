from __future__ import annotations

import logging
import re
from typing import Any

from endpoint_tool_sdk.security import redact_sensitive_fields


_SECRET_RE = re.compile(
    r"(?i)(authorization|access_token|api_key|cookie|password|secret|token)([=:]\s*)([^,\s;]+)"
)


def redact_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_sensitive_fields(record.args)
            else:
                record.args = tuple(redact_text(item) for item in record.args)
        return True


def setup_logging(*, level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, str(level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    root = logging.getLogger()
    if not any(isinstance(item, RedactingFilter) for item in root.filters):
        root.addFilter(RedactingFilter())

