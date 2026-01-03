"""Service runner registration helpers."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

from orchestrai.finalize import connect_on_app_finalize

if TYPE_CHECKING:  # pragma: no cover
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


def register_service_runner(
    name: str,
    runner: BaseServiceRunner | type[BaseServiceRunner] | Callable[..., BaseServiceRunner],
    *,
    make_default: bool = False,
    allow_override: bool = False,
) -> None:
    """Register a service runner on app finalize.

    Accepts an instance, class, or callable factory. The runner is instantiated lazily
    when the current app reaches the finalize stage.
    """

    runner_name = str(name).strip()
    if not runner_name:
        raise ValueError("service runner name must be a non-empty string")

    def _get_runner() -> BaseServiceRunner:
        if inspect.isclass(runner):
            return runner()  # type: ignore[return-value]
        if callable(runner) and not hasattr(runner, "enqueue"):
            return runner()  # type: ignore[return-value]
        return runner  # type: ignore[return-value]

    def _attach(app: Any) -> None:
        try:
            built_runner = _get_runner()
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"Failed to build service runner '{runner_name}'") from exc

        register = getattr(app, "register_service_runner", None)
        if callable(register):
            register(runner_name, built_runner)
        else:  # pragma: no cover - defensive
            raise LookupError("Current app cannot register service runners")

        current_default = getattr(app, "default_service_runner", None)
        if make_default and (allow_override or current_default is None):
            try:
                setattr(app, "default_service_runner", runner_name)
            except Exception:
                pass

    connect_on_app_finalize(_attach)


__all__ = ["BaseServiceRunner", "TaskStatus", "register_service_runner"]
