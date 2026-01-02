import asyncio
import importlib
from datetime import datetime

import pytest

from orchestrai.components.services.calls import ServiceCall, to_jsonable
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.types.transport import Response


class SyncTaskService(BaseService):
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="demo", group="svc", name="sync")

    async def arun(self, **ctx):
        return {"mode": "sync", **ctx}


class AsyncTaskService(BaseService):
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="demo", group="svc", name="async")

    async def arun(self, **ctx):
        await asyncio.sleep(0)
        return {"mode": "async", **ctx}


class EchoLifecycleService(BaseService):
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="demo", group="svc", name="echo")

    async def arun(self, **ctx):
        call = ctx.get("call")
        return {
            "value": ctx.get("value"),
            "call_id": getattr(call, "id", None),
            "has_call": call is not None,
        }


class ErrorService(BaseService):
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="demo", group="svc", name="error")

    async def arun(self, **ctx):
        raise RuntimeError("boom")


def test_task_run_executes_inline():
    sync_call = SyncTaskService().task.run(foo=1)

    assert isinstance(sync_call, ServiceCall)
    assert sync_call.status == "succeeded"
    assert sync_call.result["mode"] == "sync"
    assert sync_call.dispatch["service"] == SyncTaskService.identity.as_str


@pytest.mark.asyncio
async def test_task_arun_executes_inline():
    async_call = await AsyncTaskService().task.arun(bar=2)

    assert isinstance(async_call, ServiceCall)
    assert async_call.status == "succeeded"
    assert async_call.result["bar"] == 2
    assert async_call.dispatch["service"] == AsyncTaskService.identity.as_str


def test_task_using_queue_is_rejected():
    with pytest.raises(ValueError):
        SyncTaskService.task.using(queue="hi-priority")


def test_runner_style_using_is_blocked():
    with pytest.raises(RuntimeError, match="task\\.using"):
        SyncTaskService.using(queue="legacy-runner")


def test_legacy_runner_imports_are_guarded():
    with pytest.raises(ImportError):
        importlib.import_module("orchestrai.components.services.runners")
    with pytest.raises(ImportError):
        importlib.import_module("orchestrai.components.services.dispatch")


def test_to_jsonable_serializes_response_result():
    call = ServiceCall(
        id="1",
        status="succeeded",
        input={},
        context=None,
        result=Response(output=[]),
        error=None,
        dispatch={"service": SyncTaskService.identity.as_str},
        created_at=datetime.now(),
    )

    payload = to_jsonable(call)

    assert payload["result"]["output"] == []
    assert payload["dispatch"]["service"] == SyncTaskService.identity.as_str


def test_execute_returns_raw_result():
    service = EchoLifecycleService()

    result = service.execute(value=3)

    assert isinstance(result, dict)
    assert result["value"] == 3
    assert result["has_call"] is False


def test_call_returns_service_call_and_injects_call_into_payload():
    service = EchoLifecycleService()

    call = service.call(payload={"value": 5})

    assert isinstance(call, ServiceCall)
    assert call.status == "succeeded"
    assert call.result["value"] == 5
    assert call.result["call_id"] == call.id
    assert call.result["has_call"] is True
    assert call.dispatch["service"] == EchoLifecycleService.identity.as_str
    assert call.started_at is not None and call.finished_at is not None


@pytest.mark.asyncio
async def test_acall_returns_service_call_and_injects_call_into_payload():
    service = EchoLifecycleService()

    call = await service.acall(payload={"value": 7})

    assert isinstance(call, ServiceCall)
    assert call.status == "succeeded"
    assert call.result["value"] == 7
    assert call.result["call_id"] == call.id
    assert call.result["has_call"] is True
    assert call.dispatch["service"] == EchoLifecycleService.identity.as_str
    assert call.started_at is not None and call.finished_at is not None


def test_call_records_failure_and_error_message():
    service = ErrorService()

    call = service.call()

    assert isinstance(call, ServiceCall)
    assert call.status == "failed"
    assert call.result is None
    assert call.error
