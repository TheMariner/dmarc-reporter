"""Structured logging helpers with basic secret redaction."""

from __future__ import annotations

import logging
import re
from typing import Iterable


DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
REDACTION_PATTERNS = (
    re.compile(r"(access[_-]?token=)([^&\s]+)", re.IGNORECASE),
    re.compile(r"(refresh[_-]?token=)([^&\s]+)", re.IGNORECASE),
    re.compile(r'("access_token"\s*:\s*")([^"]+)(")', re.IGNORECASE),
    re.compile(r'("refresh_token"\s*:\s*")([^"]+)(")', re.IGNORECASE),
    re.compile(r'("client_secret"\s*:\s*")([^"]+)(")', re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)(\S+)", re.IGNORECASE),
    re.compile(r"(Bearer\s+)(eyJ[\w.-]+)", re.IGNORECASE),
    re.compile(r"(client_secret[^:=]*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(token[^:=]*[:=]\s*)(\S+)", re.IGNORECASE),
)


class RedactingFilter(logging.Filter):
    """Redact sensitive values before they are emitted."""

    def __init__(self, patterns: Iterable[re.Pattern[str]] = REDACTION_PATTERNS) -> None:
        super().__init__()
        self._patterns = tuple(patterns)

    def filter(self, record: logging.LogRecord) -> bool:
        message = redact_text(record.getMessage(), self._patterns)
        record.msg = message
        record.args = ()
        return True


def redact_text(message: str, patterns: Iterable[re.Pattern[str]] = REDACTION_PATTERNS) -> str:
    """Redact sensitive tokens from arbitrary text."""
    redacted = message
    for pattern in patterns:
        groups = pattern.groups
        if groups >= 3:
            redacted = pattern.sub(r"\1[REDACTED]\3", redacted)
        else:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def configure_logging(*, verbose: bool = False, log_level: str = "INFO") -> None:
    """Configure root logging once for the application."""
    level_name = "DEBUG" if verbose else log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        root_logger.addHandler(handler)

    for handler in root_logger.handlers:
        handler.addFilter(RedactingFilter())


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)


def log_workflow_summary(logger: logging.Logger, workflow: str, **fields: object) -> None:
    """Emit a concise workflow summary with stable key/value fields."""
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("%s_summary %s", workflow, details)
