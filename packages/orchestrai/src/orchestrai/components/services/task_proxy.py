"""
Task proxy utilities for service execution.

This module provides the ServiceSpec dataclass for configuring service
instantiation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from orchestrai.components.services.calls.mixins import ServiceCallMixin

if TYPE_CHECKING:
    from orchestrai.components.services.service import CoreTaskProxy


@dataclass(frozen=True)
class ServiceSpec:
    """Configuration spec for building a service instance.

    This dataclass holds the service class and constructor kwargs,
    enabling deferred instantiation via task proxies.
    """

    service_cls: type[ServiceCallMixin]
    service_kwargs: dict[str, Any]

    def using(self, **service_kwargs: Any) -> ServiceSpec:
        """Create a new ServiceSpec with merged kwargs."""
        merged = {**self.service_kwargs, **service_kwargs}
        return ServiceSpec(self.service_cls, merged)

    @property
    def task(self) -> CoreTaskProxy:
        """Get a task proxy for this service spec."""
        from orchestrai.components.services.service import CoreTaskProxy

        return CoreTaskProxy(self)


__all__ = ["ServiceSpec"]
