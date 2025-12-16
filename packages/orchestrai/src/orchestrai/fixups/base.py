"""Fixup interfaces and built-in helpers."""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Any, Protocol, runtime_checkable


class FixupStage(Enum):
    """Lifecycle checkpoints that fixups can observe."""

    CONFIGURE_PRE = auto()
    CONFIGURE_POST = auto()
    START_PRE = auto()
    START_POST = auto()
    AUTODISCOVER_PRE = auto()
    AUTODISCOVER_POST = auto()
    FINALIZE_PRE = auto()
    FINALIZE_POST = auto()
    ENSURE_READY_PRE = auto()
    ENSURE_READY_POST = auto()


@runtime_checkable
class Fixup(Protocol):
    """A callable hook invoked at lifecycle checkpoints."""

    def apply(self, stage: FixupStage, app: Any, **context: Any) -> Any:
        ...


class NoOpFixup:
    """A fixup that intentionally does nothing."""

    def apply(self, stage: FixupStage, app: Any, **context: Any) -> None:  # pragma: no cover
        return None


class LoggingFixup:
    """Log every lifecycle stage observed by the application."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    def apply(self, stage: FixupStage, app: Any, **context: Any) -> None:
        self.logger.info("[%s] %s", app.name, stage.name)


__all__ = ["Fixup", "FixupStage", "LoggingFixup", "NoOpFixup"]
