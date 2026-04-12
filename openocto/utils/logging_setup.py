"""Logging configuration — console + optional rotating file handler."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from openocto.config import LoggingConfig

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def setup_logging(config: LoggingConfig) -> None:
    """Initialize root logger from config.

    Always installs a console handler.  If ``config.file`` is set, also
    installs a rotating file handler at that path.  Idempotent: replaces
    any pre-existing handlers so reconfiguration during tests/dev works.
    """
    root = logging.getLogger()
    root.setLevel(_parse_level(config.level))

    # Drop any handlers from a prior call so we don't double-log.
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if config.file:
        log_path = Path(config.file).expanduser()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=config.max_bytes,
                backupCount=config.backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
            root.info("File logging enabled: %s", log_path)
        except OSError as e:
            root.warning("Could not open log file %s: %s", log_path, e)

    # Silence noisy third-party loggers — aiohttp.access logs every HTTP
    # request at INFO, which spams the console once chat polling kicks in.
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def _parse_level(level: str) -> int:
    return getattr(logging, level.upper(), logging.INFO)
