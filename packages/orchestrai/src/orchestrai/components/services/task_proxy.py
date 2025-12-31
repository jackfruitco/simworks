from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from orchestrai.components.services.execution import ExecutionLifecycleMixin


@dataclass(frozen=True)
class ServiceSpec:
    service_cls: type[ExecutionLifecycleMixin]
    service_kwargs: dict[str, Any]

    def using(self, **service_kwargs: Any) -> "ServiceSpec":
        merged = {**self.service_kwargs, **service_kwargs}
        return ServiceSpec(self.service_cls, merged)

    @property
    def task(self) -> "CoreTaskProxy":
        return CoreTaskProxy(self)


class CoreTaskProxy:
    """Proxy for executing a service inline via its lifecycle helpers."""

    def __init__(self, spec: ServiceSpec):
        self._spec = spec

    def _build(self) -> ExecutionLifecycleMixin:
        return self._spec.service_cls(**self._spec.service_kwargs)

    def using(self, **service_kwargs: Any) -> "CoreTaskProxy":
        if "queue" in service_kwargs:
            raise ValueError("queue dispatch is not supported for inline tasks")
        return CoreTaskProxy(self._spec.using(**service_kwargs))

    def run(self, **payload: Any):
        service = self._build()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                service._run_call(
                    payload=payload,
                    context=getattr(service, "context", None),
                    dispatch=self._dispatch_meta(service),
                )
            )

        if loop.is_running():
            raise RuntimeError("Cannot run inline task while an event loop is already running")

        return loop.run_until_complete(
            service._run_call(
                payload=payload,
                context=getattr(service, "context", None),
                dispatch=self._dispatch_meta(service),
            )
        )

    async def arun(self, **payload: Any):
        service = self._build()
        return await service._run_call(
            payload=payload,
            context=getattr(service, "context", None),
            dispatch=self._dispatch_meta(service),
        )

    def _dispatch_meta(self, service: ExecutionLifecycleMixin) -> dict[str, Any]:
        identity = getattr(service, "identity", None)
        ident_str = getattr(identity, "as_str", None)
        return {"service": ident_str or service.__class__.__name__}


class TaskDescriptor:
    def __get__(self, instance: Any, owner: type | None = None) -> CoreTaskProxy:
        service_cls = owner or type(instance)
        kwargs: dict[str, Any] = {}
        if instance is not None:
            context = getattr(instance, "context", None)
            if context is not None:
                try:
                    kwargs["context"] = dict(context)
                except Exception:
                    kwargs["context"] = context
        return CoreTaskProxy(ServiceSpec(service_cls, kwargs))


__all__ = ["CoreTaskProxy", "ServiceSpec", "TaskDescriptor"]
