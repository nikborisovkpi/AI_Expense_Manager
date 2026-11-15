"""Safe structured logging configuration (never logs raw receipt content or secrets)."""

from __future__ import annotations

import logging


def configure_logging(environment: str = "development") -> None:
    level = logging.DEBUG if environment == "development" else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
