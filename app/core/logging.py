"""Logging setup.

The log line format is plain text so journald and Docker can both read it.
Secrets are never passed to the logger by this module.
"""

import logging
from pathlib import Path


def configure_logging(level: str, log_file: Path | None = None) -> None:
    """Configure the application logger. Safe to call more than once."""

    logger = logging.getLogger("news_reels")
    logger.handlers.clear()
    logger.setLevel(level.upper())
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
