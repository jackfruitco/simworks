from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from orchestrai.components.services.calls import ServiceCall, assert_jsonable
from orchestrai.components.services.execution import ExecutionLifecycleMixin
from orchestrai.components.services.task_proxy import ServiceSpec


def _split_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    service_kwargs: dict[str, Any] = {}
    dispatch_kwargs: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in {"queue", "backend", "task_id"}:
            dispatch_kwargs[key] = value
        else:
            service_kwargs[key] = value
    return service_kwargs, dispatch_kwargs


@dataclass(frozen=True)
class DjangoServiceSpec(ServiceSpec):
    dispatch_kwargs: dict[str, Any] | None = None

    def using(self, **service_kwargs: Any) -> "DjangoServiceSpec":
        svc_kwargs, dispatch_kwargs = _split_kwargs(service_kwargs)
        merged_dispatch = {**(self.dispatch_kwargs or {}), **dispatch_kwargs}
        merged_service = {**self.service_kwargs, **svc_kwargs}
        return DjangoServiceSpec(self.service_cls, merged_service, merged_dispatch)

    @property
    def task(self) -> "DjangoTaskProxy":
        return DjangoTaskProxy(self)


class DjangoTaskProxy:
    """Django-aware task proxy that persists :class:`ServiceCall` records."""

    def __init__(self, spec: DjangoServiceSpec):
        self._spec = spec

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------
    def _build(self) -> ExecutionLifecycleMixin:
        return self._spec.service_cls(**self._spec.service_kwargs)

    def using(self, **service_kwargs: Any) -> "DjangoTaskProxy":
        return DjangoTaskProxy(self._spec.using(**service_kwargs))

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------
    def _build_dispatch(self, service: ExecutionLifecycleMixin) -> dict[str, Any]:
        dispatch = {"service": getattr(getattr(service, "identity", None), "as_str", None)}
        if self._spec.dispatch_kwargs:
            dispatch.update(self._spec.dispatch_kwargs)
        dispatch.setdefault("backend", "immediate")
        return dispatch

    def _persist_call(self, call: ServiceCall, dispatch: dict[str, Any]) -> Any:
        from orchestrai_django.models import ServiceCallRecord
        from django.utils import timezone

        backend = dispatch.get("backend") or "immediate"
        queue = dispatch.get("queue")
        task_id = dispatch.get("task_id")

        assert_jsonable(self._spec.service_kwargs, path="service_kwargs")

        record = ServiceCallRecord(
            id=call.id,
            service_identity=dispatch.get("service") or call.dispatch.get("service"),
            service_kwargs=self._spec.service_kwargs,
            backend=backend,
            queue=queue,
            task_id=task_id,
            status=call.status,
            input=call.input,
            context=call.context,
            result=call.result,
            error=call.error,
            dispatch=dispatch,
            created_at=timezone.make_aware(call.created_at)
            if call.created_at and not timezone.is_aware(call.created_at)
            else call.created_at,
            started_at=timezone.make_aware(call.started_at)
            if call.started_at and not timezone.is_aware(call.started_at)
            else call.started_at,
            finished_at=timezone.make_aware(call.finished_at)
            if call.finished_at and not timezone.is_aware(call.finished_at)
            else call.finished_at,
        )
        record.save(force_insert=True)
        return record

    def _dispatch_immediate(self, call_id: str) -> Any:
        from orchestrai_django.tasks import run_service_call

        return run_service_call(call_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def enqueue(self, **payload: Any):
        service = self._build()
        dispatch = self._build_dispatch(service)
        call = service._create_call(
            payload=payload,
            context=getattr(service, "context", None),
            dispatch=dispatch,
        )

        if dispatch.get("backend") not in {None, "immediate"}:
            call.status = "queued"

        record = self._persist_call(call, dispatch)

        backend = dispatch.get("backend") or "immediate"
        if backend == "immediate":
            return self._dispatch_immediate(record.id)

        return record

    async def aenqueue(self, **payload: Any):
        service = self._build()
        dispatch = self._build_dispatch(service)
        call = service._create_call(
            payload=payload,
            context=getattr(service, "context", None),
            dispatch=dispatch,
        )

        if dispatch.get("backend") not in {None, "immediate"}:
            call.status = "queued"

        record = self._persist_call(call, dispatch)

        backend = dispatch.get("backend") or "immediate"
        if backend == "immediate":
            return await asyncio.to_thread(self._dispatch_immediate, record.id)

        return record

    # Compatibility helpers (inline execution)
    def run(self, **payload: Any):
        service = self._build()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                service._run_call(
                    payload=payload,
                    context=getattr(service, "context", None),
                    dispatch=self._build_dispatch(service),
                )
            )

        if loop.is_running():
            raise RuntimeError("Cannot run inline task while an event loop is already running")

        return loop.run_until_complete(
            service._run_call(
                payload=payload,
                context=getattr(service, "context", None),
                dispatch=self._build_dispatch(service),
            )
        )

    async def arun(self, **payload: Any):
        service = self._build()
        return await service._run_call(
            payload=payload,
            context=getattr(service, "context", None),
            dispatch=self._build_dispatch(service),
        )


class DjangoTaskDescriptor:
    def __get__(self, instance: Any, owner: type | None = None) -> DjangoTaskProxy:
        service_cls = owner or type(instance)
        kwargs: dict[str, Any] = {}
        if instance is not None:
            context = getattr(instance, "context", None)
            if context is not None:
                try:
                    kwargs["context"] = dict(context)
                except Exception:
                    kwargs["context"] = context
        return DjangoTaskProxy(DjangoServiceSpec(service_cls, kwargs, {}))


def use_django_task_proxy() -> None:
    """Swap :class:`BaseService.task` to the Django task descriptor if available."""

    try:
        import importlib.util

        if importlib.util.find_spec("orchestrai_django") is None:
            return
    except Exception:
        return

    try:
        from orchestrai.components.services.service import BaseService
    except Exception:
        return

    if isinstance(getattr(BaseService, "task", None), DjangoTaskDescriptor):
        return

    try:
        BaseService.task = DjangoTaskDescriptor()
    except Exception:
        return


__all__ = [
    "DjangoServiceSpec",
    "DjangoTaskProxy",
    "DjangoTaskDescriptor",
    "use_django_task_proxy",
]
