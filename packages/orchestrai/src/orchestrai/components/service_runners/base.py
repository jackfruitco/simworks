"""Service runner registration helpers."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Protocol

from orchestrai.finalize import connect_on_app_finalize


class ServiceRunner(Protocol):
    def start(self, **payload: Any) -> Any: ...

    def enqueue(self, **payload: Any) -> Any: ...


def register_service_runner(
    name: str,
    runner: ServiceRunner | type[ServiceRunner] | Callable[..., ServiceRunner],
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

    def _get_runner() -> ServiceRunner:
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


__all__ = ["ServiceRunner", "register_service_runner"]
