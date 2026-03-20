"""Task proxy utilities for service execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orchestrai.components.services.calls.mixins import ServiceCallMixin


@dataclass(frozen=True)
class ServiceSpec:
    """Configuration spec for building a service instance.

    This dataclass holds the service class and constructor kwargs,
    enabling deferred instantiation via task proxies.
    """

    service_cls: type[ServiceCallMixin]
    service_kwargs: dict[str, Any]
    dispatch_kwargs: dict[str, Any] | None = None

    def using(self, **service_kwargs: Any) -> ServiceSpec:
        """Create a new ServiceSpec with merged service and dispatch kwargs."""
        dispatch_keys = {"queue", "backend", "task_id"}
        merged_service = {**self.service_kwargs}
        merged_dispatch = {**(self.dispatch_kwargs or {})}

        for key, value in service_kwargs.items():
            if key in dispatch_keys:
                merged_dispatch[key] = value
            else:
                merged_service[key] = value

        return ServiceSpec(
            self.service_cls,
            merged_service,
            merged_dispatch or None,
        )

    @property
    def task(self):
        """Get a task proxy for this service spec."""
        from orchestrai.components.services.service import resolve_task_proxy

        return resolve_task_proxy(self)


__all__ = ["ServiceSpec"]
