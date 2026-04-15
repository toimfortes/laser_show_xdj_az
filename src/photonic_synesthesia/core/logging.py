"""Logging compatibility helpers with optional structlog support."""

from __future__ import annotations

import logging
from typing import Any

_structlog: Any = None

try:  # pragma: no cover - exercised when structlog is installed
    import structlog as _structlog_import
except ImportError:  # pragma: no cover - exercised in minimal test envs
    pass
else:  # pragma: no cover - exercised when structlog is installed
    _structlog = _structlog_import


class _CompatLogger:
    """Minimal logger wrapper that accepts structlog-style kwargs."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, **kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, event, **kwargs)

    def _log(self, level: int, event: str, **kwargs: Any) -> None:
        if kwargs:
            formatted = ", ".join(f"{key}={value!r}" for key, value in sorted(kwargs.items()))
            self._logger.log(level, "%s | %s", event, formatted)
        else:
            self._logger.log(level, "%s", event)


def get_logger(name: str | None = None) -> Any:
    """Return a logger compatible with structlog-style call sites."""
    if _structlog is not None:
        return _structlog.get_logger(name)
    return _CompatLogger(logging.getLogger(name if name else "photonic_synesthesia"))


def configure_logging(log_level: int) -> None:
    """Configure logging for either structlog or stdlib logging."""
    if _structlog is not None:
        _structlog.configure(
            wrapper_class=_structlog.make_filtering_bound_logger(log_level),
        )
    else:
        logging.basicConfig(level=log_level)
