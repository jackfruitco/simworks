from __future__ import annotations

import asyncio
import logging
from typing import Any

from orchestrai.components.services.calls import ServiceCall, assert_jsonable
from orchestrai.components.services.calls.mixins import ServiceCallMixin
from orchestrai.components.services.service import register_task_proxy_factory
from orchestrai.components.services.task_proxy import ServiceSpec
from orchestrai.orm_mode import must_be_async, must_be_sync

logger = logging.getLogger(__name__)


class DjangoTaskProxy:
    """Django-aware task proxy that persists :class:`ServiceCall` records."""

    def __init__(self, spec: ServiceSpec):
        self._spec = spec

    def _build(self) -> ServiceCallMixin:
        return self._spec.service_cls(**self._spec.service_kwargs)

    def using(self, **service_kwargs: Any) -> DjangoTaskProxy:
        return DjangoTaskProxy(self._spec.using(**service_kwargs))

    def _build_dispatch(self, service: ServiceCallMixin) -> dict[str, Any]:
        dispatch = {"service": getattr(getattr(service, "identity", None), "as_str", None)}
        if self._spec.dispatch_kwargs:
            dispatch.update(self._spec.dispatch_kwargs)
        dispatch.setdefault("backend", "immediate")
        return dispatch

    def _build_record(self, call: ServiceCall, dispatch: dict[str, Any]):
        from django.utils import timezone

        from orchestrai_django.models import ServiceCall as ServiceCallModel

        backend = dispatch.get("backend") or "immediate"
        queue = dispatch.get("queue")
        task_id = dispatch.get("task_id")

        assert_jsonable(self._spec.service_kwargs, path="service_kwargs")

        service_cls = self._spec.service_cls
        schema_cls = getattr(service_cls, "response_schema", None)
        schema_fqn = f"{schema_cls.__module__}.{schema_cls.__qualname__}" if schema_cls else None

        return ServiceCallModel(
            id=call.id,
            service_identity=dispatch.get("service") or call.dispatch.get("service"),
            service_kwargs=self._spec.service_kwargs,
            schema_fqn=schema_fqn,
            backend=backend,
            queue=queue,
            task_id=task_id,
            status=call.status,
            input=call.input,
            context=call.context,
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

    def _persist_call_sync(self, call: ServiceCall, dispatch: dict[str, Any]) -> Any:
        must_be_sync()
        record = self._build_record(call, dispatch)
        record.save(force_insert=True)
        return record

    async def _persist_call_async(self, call: ServiceCall, dispatch: dict[str, Any]) -> Any:
        must_be_async()
        record = self._build_record(call, dispatch)
        await record.asave(force_insert=True)
        return record

    def _dispatch_immediate(self, call_id: str) -> Any:
        """Dispatch a service call via the Django Tasks framework."""
        from orchestrai_django.tasks import run_service_call_task

        task_result = run_service_call_task.enqueue(call_id=call_id)
        logger.debug(
            "DjangoTaskProxy: Enqueued service call %s as Django task %s", call_id, task_result.id
        )
        return task_result.id

    def enqueue(self, **payload: Any):
        must_be_sync()
        service = self._build()
        dispatch = self._build_dispatch(service)
        call = service._create_call(
            payload=payload,
            context=getattr(service, "context", None),
            dispatch=dispatch,
        )

        if dispatch.get("backend") not in {None, "immediate"}:
            call.status = "queued"

        record = self._persist_call_sync(call, dispatch)

        backend = dispatch.get("backend") or "immediate"
        if backend == "immediate":
            task_id = self._dispatch_immediate(record.id)
            record.task_id = task_id
            record.save(update_fields=["task_id"])

        return record.id

    async def aenqueue(self, **payload: Any):
        must_be_async()

        async def _run() -> str:
            service = self._build()
            dispatch = self._build_dispatch(service)
            call = service._create_call(
                payload=payload,
                context=getattr(service, "context", None),
                dispatch=dispatch,
            )

            if dispatch.get("backend") not in {None, "immediate"}:
                call.status = "queued"

            record = await self._persist_call_async(call, dispatch)

            backend = dispatch.get("backend") or "immediate"
            if backend == "immediate":
                task_id = self._dispatch_immediate(record.id)
                record.task_id = task_id
                await record.asave(update_fields=["task_id"])

            return record.id

        try:
            return await asyncio.shield(_run())
        except asyncio.CancelledError:
            logger.debug("aenqueue cancelled by caller; dispatch shielded", exc_info=True)
            raise

    def run(self, **payload: Any):
        service = self._build()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return service.call(
                payload=payload,
                context=getattr(service, "context", None),
                dispatch=self._build_dispatch(service),
            )

        if loop.is_running():
            raise RuntimeError("Cannot run inline task while an event loop is already running")

        return loop.run_until_complete(
            service.acall(
                payload=payload,
                context=getattr(service, "context", None),
                dispatch=self._build_dispatch(service),
            )
        )

    async def arun(self, **payload: Any):
        service = self._build()
        return await service.acall(
            payload=payload,
            context=getattr(service, "context", None),
            dispatch=self._build_dispatch(service),
        )


def django_task_proxy_factory(spec: Any) -> DjangoTaskProxy | None:
    if not isinstance(spec, ServiceSpec):
        return None
    return DjangoTaskProxy(spec)


def use_django_task_proxy() -> None:
    register_task_proxy_factory(django_task_proxy_factory)


__all__ = ["DjangoTaskProxy", "django_task_proxy_factory", "use_django_task_proxy"]
