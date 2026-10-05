"""Logging setup.

Secrets must never reach a log file. :class:`RedactingFilter` scrubs anything
that looks like an API key or a Basic/Bearer credential, and is attached to
every handler so a careless ``logger.info(request.headers)`` cannot leak a key.
"""

from __future__ import annotations

import logging
import logging.config
import re
from typing import Any

# Anything matching these is replaced before it is written.
_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"), r"\1 ***"),
    (re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/=]{8,}"), r"\1 ***"),
    # key=value / "key": "value" shapes
    (
        re.compile(
            r"(?i)\b(api[_-]?key|api[_-]?secret|secret|password|token|access[_-]?key)"
            r"\b(\s*[:=]\s*)([\"']?)([^\s\"',}]{6,})\3"
        ),
        r"\1\2\3***\3",
    ),
    # TypeSafe keys and long opaque blobs
    (re.compile(r"\bts_[A-Za-z0-9]{16,}\b"), "ts_***"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "sk-***"),
]


def redact(text: str) -> str:
    """Return ``text`` with credential-shaped substrings masked."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrites the formatted message so no handler can receive a raw secret."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


class BriefFormatter(logging.Formatter):
    """Readable single-line logs for a foreground container."""

    def format(self, record: logging.LogRecord) -> str:
        record.shortlevel = record.levelname[:4]
        return super().format(record)


def configure_logging(level: str = "INFO", *, quiet_libraries: bool = True) -> None:
    """Install handlers once. Safe to call repeatedly."""
    root = logging.getLogger()
    if getattr(root, "_awltux_configured", False):
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        BriefFormatter(
            fmt="%(asctime)s %(shortlevel)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter())

    root.handlers = [handler]
    root.setLevel(level.upper())
    root._awltux_configured = True  # type: ignore[attr-defined]

    if quiet_libraries:
        # These are chatty and never useful at INFO for our purposes.
        for name in ("httpx", "httpcore", "urllib3", "yfinance", "peewee", "apscheduler"):
            logging.getLogger(name).setLevel(logging.WARNING)


def logger_config_dict(level: str = "INFO") -> dict[str, Any]:
    """dictConfig form, if a deployment prefers to configure logging externally."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"redact": {"()": RedactingFilter}},
        "formatters": {
            "brief": {
                "()": BriefFormatter,
                "format": "%(asctime)s %(shortlevel)s %(name)s: %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "brief",
                "filters": ["redact"],
            }
        },
        "root": {"level": level.upper(), "handlers": ["console"]},
    }
