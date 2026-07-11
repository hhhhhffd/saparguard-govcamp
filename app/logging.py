from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import Settings


def configure_logging(config: Settings) -> None:
    """Configure console and rotating file logs without exposing secrets."""
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
    )
    file_handler = RotatingFileHandler(
        config.log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        handlers=[console_handler, file_handler],
        force=True,
    )
