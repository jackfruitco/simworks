import asyncio
import importlib

import pytest

from orchestrai.components.services.calls import ServiceCall
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN


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


def test_legacy_runner_imports_are_guarded():
    with pytest.raises(ImportError):
        importlib.import_module("orchestrai.components.services.runners")
    with pytest.raises(ImportError):
        importlib.import_module("orchestrai.components.services.dispatch")
