"""Base protocol for service runner integrations.

Service runners coordinate the execution lifecycle for services, whether they
run inline or dispatch to external systems. The protocol stays lightweight so
it can be referenced from type hints without pulling in optional integrations
such as Django.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - only used for type checking
    from orchestrai.components.services.service import BaseService


@dataclass(slots=True)
class TaskStatus:
    """Status payload returned by service runners."""

    id: str
    state: str
    result: Any | None = None
    error: Exception | str | None = None


@runtime_checkable
class BaseServiceRunner(Protocol):
    """Minimal interface runners should expose to :class:`ServiceCall`."""

    def start(
        self,
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Execute the service synchronously, returning a result or response."""

    def enqueue(
        self,
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> TaskStatus | Any:
        """Queue the service for async execution and return task metadata."""

    def stream(
        self,
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Optional streaming interface for runners that support it."""

    def get_status(
        self,
        *,
        service_cls: type[BaseService],
        service_kwargs: dict[str, Any],
        phase: str,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> TaskStatus | Any:
        """Retrieve the latest status for an enqueued service run."""


__all__ = ["BaseServiceRunner", "TaskStatus"]
