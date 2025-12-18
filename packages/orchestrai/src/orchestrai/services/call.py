from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, TYPE_CHECKING

from orchestrai._state import get_current_app

if TYPE_CHECKING:  # pragma: no cover
    from orchestrai.components.services.service import BaseService


def _coerce_runner_name(service_cls: type[BaseService], explicit: str | None) -> str:
    if explicit:
        return explicit

    identity = getattr(service_cls, "identity", None)
    label = getattr(identity, "name", None) or getattr(identity, "as_str", None)
    if label:
        return str(label)

    return getattr(service_cls, "__name__", "<unknown service>")


@dataclass(frozen=True)
class ServiceCall:
    service_cls: type[BaseService]
    service_kwargs: dict[str, Any] = field(default_factory=dict)
    runner_name: str | None = None
    runner_kwargs: dict[str, Any] = field(default_factory=dict)
    phase: str = "service"

    def using(self, **service_kwargs: Any) -> "ServiceCall":
        """Return a new call with updated service kwargs."""
        merged = {**self.service_kwargs, **service_kwargs}
        return replace(self, service_kwargs=merged)

    def with_runner(self, name: str | None = None, **runner_kwargs: Any) -> "ServiceCall":
        """Return a new call with runner selection/kwargs applied."""
        merged_kwargs = {**self.runner_kwargs, **runner_kwargs}
        return replace(self, runner_name=name or self.runner_name, runner_kwargs=merged_kwargs)

    def _resolve_runner(self) -> tuple[str, Any]:
        app = get_current_app()
        runners = getattr(app, "service_runners", None)
        if runners is None:
            raise LookupError("Current app does not expose service runners")

        runner_name = _coerce_runner_name(self.service_cls, self.runner_name)

        try:
            runner = runners[runner_name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise LookupError(f"Service runner '{runner_name}' is not registered") from exc

        return runner_name, runner

    def _dispatch(
        self,
        method_name: str,
        *,
        service_kwargs: dict[str, Any] | None = None,
        runner_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        call = self
        if service_kwargs:
            call = call.using(**service_kwargs)
        if runner_kwargs:
            call = call.with_runner(**runner_kwargs)

        runner_name, runner = call._resolve_runner()
        runner_method = getattr(runner, method_name, None)
        if not callable(runner_method):
            raise AttributeError(
                f"Service runner '{runner_name}' does not implement '{method_name}'"
            )

        payload: dict[str, Any] = {
            "service_cls": call.service_cls,
            "service_kwargs": dict(call.service_kwargs),
            "phase": call.phase,
        }
        if call.runner_kwargs:
            payload["runner_kwargs"] = dict(call.runner_kwargs)

        return runner_method(**payload)

    def enqueue(self, **service_kwargs: Any) -> Any:
        """Queue this service call if the runner supports it."""
        return self._dispatch("enqueue", service_kwargs=service_kwargs)

    def stream(self, **service_kwargs: Any) -> Any:
        """Stream results from the runner, when available."""
        return self._dispatch("stream", service_kwargs=service_kwargs)

    def get_status(self, **runner_kwargs: Any) -> Any:
        """Query status for this call from the runner, when available."""
        return self._dispatch("get_status", runner_kwargs=runner_kwargs)

    def start(self, **service_kwargs: Any) -> Any:
        """Start the service execution through the configured runner."""
        return self._dispatch("start", service_kwargs=service_kwargs)
