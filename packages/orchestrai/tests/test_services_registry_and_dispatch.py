import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from orchestrai._state import push_current_app
from orchestrai.components.services.dispatch import ServiceCall, _coerce_runner_name, dispatch_service
from orchestrai.components.services.discovery import discover_services, list_services
from orchestrai.components.services.exceptions import (
    MissingRequiredContextKeys,
    ServiceDispatchError,
    ServiceDiscoveryError,
    ServiceCodecResolutionError,
    ServiceBuildRequestError,
    ServiceStreamError,
)
from orchestrai.components.services.registry import ServiceRegistry, ensure_service_registry
from orchestrai.components.services.runners import LocalServiceRunner, register_service_runner
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.registry.active_app import push_active_registry_app
from orchestrai.registry.base import ComponentRegistry
from orchestrai.registry.component_store import ComponentStore


class EchoService(BaseService):
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="tests", group="echo", name="svc")

    def execute(self, **kwargs):
        return {**kwargs}

    async def aexecute(self, **kwargs):
        return {**kwargs}


class AsyncEchoService(BaseService):
    abstract = False

    async def aexecute(self, **kwargs):
        return {**kwargs}


class DummyEmitter:
    def emit_request(self, *args, **kwargs):
        return None

    def emit_response(self, *args, **kwargs):
        return None

    def emit_failure(self, *args, **kwargs):
        return None

    def emit_stream_chunk(self, *args, **kwargs):
        return None

    def emit_stream_complete(self, *args, **kwargs):
        return None


class SyncOnlyService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def execute(self, **kwargs):
        return {"mode": "sync", **self.kwargs, **kwargs}


class AsyncOnlyService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def aexecute(self, **kwargs):
        return {"mode": "async", **kwargs}


class StreamService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run_stream(self, **kwargs):
        return {"mode": "stream", **kwargs}


class AsyncStreamService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def run_stream(self, **kwargs):
        return {"mode": "astream", **kwargs}


class NoExecuteService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_ensure_service_registry_upgrades_plain_registry():
    store = ComponentStore()
    store._registries[SERVICES_DOMAIN] = ComponentRegistry()
    store._registries[SERVICES_DOMAIN].register(EchoService)
    app = SimpleNamespace(component_store=store)

    with push_active_registry_app(app):
        registry = ensure_service_registry()

    assert isinstance(registry, ServiceRegistry)
    assert registry.get(EchoService) is EchoService


def test_ensure_service_registry_without_store_raises(monkeypatch):
    from orchestrai.components.services import registry as registry_module

    monkeypatch.setattr(registry_module, "get_component_store", lambda app=None: None)
    with pytest.raises(LookupError):
        registry_module.ensure_service_registry()


def test_discover_services_happy_path_and_missing_module():
    assert discover_services(["math"]) == ["math"]

    with pytest.raises(ServiceDiscoveryError):
        discover_services(["nonexistent.discovery.module"])


def test_dispatch_service_missing_runner_errors():
    call = ServiceCall(service_cls=EchoService)
    with push_current_app(SimpleNamespace(service_runners={})), pytest.raises(ServiceDispatchError):
        call.start()


def test_dispatch_service_rejects_missing_method():
    call = ServiceCall(service_cls=EchoService)
    object.__setattr__(call, "_resolve_runner", lambda: ("bad", object()))

    with pytest.raises(ServiceDispatchError):
        call.stream()


def test_dispatch_service_default_runner_resolution():
    runner = LocalServiceRunner()
    app = SimpleNamespace(service_runners={"default": runner}, default_service_runner="default")

    with push_current_app(app):
        result = dispatch_service(EchoService, service_kwargs={"emitter": DummyEmitter()})

    assert result == {}


def test_register_service_runner_validates_name():
    with pytest.raises(ValueError):
        register_service_runner("", LocalServiceRunner())


def test_local_runner_rejects_sync_call_inside_event_loop():
    runner = LocalServiceRunner()

    async def invoke():
        with pytest.raises(RuntimeError):
            runner.start(service_cls=AsyncEchoService, service_kwargs={}, phase="service")

    asyncio.run(invoke())


def test_service_call_runner_kwargs_are_forwarded():
    class RecordingRunner:
        def __init__(self):
            self.seen: list[dict[str, Any]] = []

        def start(self, **payload):
            self.seen.append(payload)
            return payload

        def enqueue(self, **payload):
            self.seen.append(payload)
            return payload

        def stream(self, **payload):
            self.seen.append(payload)
            return payload

        def get_status(self, **payload):
            self.seen.append(payload)
            return payload

    runner = RecordingRunner()
    app = SimpleNamespace(service_runners={"SyncOnlyService": runner}, default_service_runner=None)
    call = ServiceCall(service_cls=SyncOnlyService, runner_kwargs={"foo": "bar"})

    with push_current_app(app):
        payload = call.start(extra=2)
        status_payload = call.get_status(state="ok")

    assert payload["runner_kwargs"] == {"foo": "bar"}
    assert runner.seen[0]["service_kwargs"]["extra"] == 2
    assert status_payload["runner_kwargs"]["state"] == "ok"


def test_service_call_requires_runner_mapping():
    call = ServiceCall(service_cls=SyncOnlyService)
    with push_current_app(SimpleNamespace(service_runners=None)), pytest.raises(ServiceDispatchError):
        call.start()


def test_service_call_rejects_non_protocol_runner():
    call = ServiceCall(service_cls=SyncOnlyService)
    app = SimpleNamespace(service_runners={"SyncOnlyService": object()}, default_service_runner=None)
    with push_current_app(app), pytest.raises(ServiceDispatchError):
        call.start()


def test_coerce_runner_name_handles_identity_failure(monkeypatch):
    class TempService(BaseService):
        abstract = False

    monkeypatch.setattr(Identity, "get_for", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    app = SimpleNamespace(default_service_runner=None)

    assert _coerce_runner_name(app, TempService, explicit=None) == "TempService"


def test_discover_services_skips_child_module_errors(monkeypatch):
    import importlib
    from orchestrai.components.services import discovery as discovery_module

    monkeypatch.setattr(importlib, "import_module", lambda name: (_ for _ in ()).throw(ModuleNotFoundError("child")))
    monkeypatch.setattr(discovery_module, "ensure_service_registry", lambda: None)

    assert discover_services(["pkg.submodule"]) == []


def test_discover_services_handles_registry_lookup_error(monkeypatch):
    from orchestrai.components.services import discovery as discovery_module

    monkeypatch.setattr(discovery_module, "ensure_service_registry", lambda: (_ for _ in ()).throw(LookupError()))
    assert discover_services([]) == []


def test_list_services_uses_registry(monkeypatch):
    class DummyRegistry:
        def __init__(self):
            self.as_str = None

        def items(self, *, as_str: bool = False):
            self.as_str = as_str
            return ("svc",)

    dummy = DummyRegistry()
    from orchestrai.components.services import discovery as discovery_module

    monkeypatch.setattr(discovery_module, "ensure_service_registry", lambda: dummy)

    assert list_services(as_str=True) == ("svc",)
    assert dummy.as_str is True


def test_local_runner_start_variants_and_errors():
    runner = LocalServiceRunner()

    assert runner.start(service_cls=SyncOnlyService, service_kwargs={"a": 1}, phase="service") == {"mode": "sync", "a": 1}
    assert runner.start(service_cls=AsyncOnlyService, service_kwargs={}, phase="service")["mode"] == "async"

    with pytest.raises(AttributeError):
        runner.start(service_cls=NoExecuteService, service_kwargs={}, phase="service")


def test_local_runner_async_paths_and_enqueue():
    runner = LocalServiceRunner()

    async def invoke():
        result_async = await runner.astart(service_cls=AsyncOnlyService, service_kwargs={}, phase="service")
        result_sync = await runner.astart(service_cls=SyncOnlyService, service_kwargs={}, phase="service")
        enqueued = await runner.aenqueue(service_cls=AsyncOnlyService, service_kwargs={}, phase="service")
        return result_async, result_sync, enqueued

    async_result, sync_result, enqueued_result = asyncio.run(invoke())

    assert async_result["mode"] == "async"
    assert sync_result["mode"] == "sync"
    assert enqueued_result["mode"] == "async"

    async def invoke_missing():
        with pytest.raises(AttributeError):
            await runner.astart(service_cls=NoExecuteService, service_kwargs={}, phase="service")

    asyncio.run(invoke_missing())


def test_local_runner_streaming_paths_and_status():
    runner = LocalServiceRunner()

    assert runner.stream(service_cls=StreamService, service_kwargs={}, phase="service")["mode"] == "stream"
    assert runner.stream(service_cls=AsyncStreamService, service_kwargs={}, phase="service")["mode"] == "astream"

    async def invoke():
        return await runner.astream(service_cls=AsyncStreamService, service_kwargs={}, phase="service")

    async def invoke_sync_stream():
        return await runner.astream(service_cls=StreamService, service_kwargs={}, phase="service")

    async def invoke_missing_stream():
        with pytest.raises(AttributeError):
            await runner.astream(service_cls=SyncOnlyService, service_kwargs={}, phase="service")

    assert asyncio.run(invoke())["mode"] == "astream"
    assert asyncio.run(invoke_sync_stream())["mode"] == "stream"
    asyncio.run(invoke_missing_stream())

    with pytest.raises(AttributeError):
        runner.stream(service_cls=SyncOnlyService, service_kwargs={}, phase="service")

    with pytest.raises(NotImplementedError):
        runner.get_status()


def test_local_runner_handles_coroutine_close_errors():
    runner = LocalServiceRunner()

    class ClosingErrorService:
        def __init__(self, **_kwargs):
            pass

        async def aexecute(self, **_kwargs):
            try:
                await asyncio.sleep(0)
            finally:
                raise RuntimeError("close failed")

    async def invoke():
        with pytest.raises(RuntimeError):
            runner.start(service_cls=ClosingErrorService, service_kwargs={}, phase="service")

    asyncio.run(invoke())


def test_run_coro_from_sync_close_error(monkeypatch):
    runner = LocalServiceRunner()

    class BadCoro:
        def __await__(self):
            if False:
                yield None
            return None

        def close(self):
            raise RuntimeError("close boom")

    monkeypatch.setattr(LocalServiceRunner, "_in_running_loop", staticmethod(lambda: True))

    with pytest.raises(RuntimeError):
        runner._run_coro_from_sync(BadCoro())


def test_register_service_runner_variants(monkeypatch):
    from orchestrai import finalize

    finalize._finalize_callbacks.clear()

    class DummyRunner:
        def __init__(self, label: str | None = None):
            self.label = label

        def start(self, **kwargs):
            return self.label or "start"

        def enqueue(self, **kwargs):
            return self.label or "enqueue"

        def stream(self, **kwargs):
            return self.label or "stream"

        def get_status(self, **kwargs):
            return self.label or "status"

    register_service_runner("cls", DummyRunner, make_default=True)
    register_service_runner("factory", lambda: DummyRunner("factory"))
    register_service_runner("instance", DummyRunner("instance"), make_default=True, allow_override=True)

    callbacks = finalize.consume_finalizers()
    app = SimpleNamespace(service_runners={}, default_service_runner="original")

    def registrar(name, runner):
        app.service_runners[name] = runner

    app.register_service_runner = registrar

    for cb in callbacks:
        cb(app)

    assert isinstance(app.service_runners["cls"], DummyRunner)
    assert app.service_runners["factory"].label == "factory"
    assert app.default_service_runner == "instance"

    finalize._finalize_callbacks.clear()


def test_register_service_runner_raises_on_build_failure(monkeypatch):
    from orchestrai import finalize

    finalize._finalize_callbacks.clear()

    class Broken:
        def __init__(self):
            raise RuntimeError("boom")

    register_service_runner("broken", Broken)
    callbacks = finalize.consume_finalizers()

    app = SimpleNamespace(register_service_runner=lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError):
        callbacks[-1](app)

    finalize._finalize_callbacks.clear()


def test_register_service_runner_handles_default_setattr_errors():
    from orchestrai import finalize

    finalize._finalize_callbacks.clear()

    class NoDefaultApp(SimpleNamespace):
        def __setattr__(self, name, value):
            if name == "default_service_runner":
                raise RuntimeError("no default")
            return super().__setattr__(name, value)

    register_service_runner("nodefault", lambda: DummyEmitter(), make_default=True, allow_override=True)
    callback = finalize.consume_finalizers()[-1]

    app = NoDefaultApp(service_runners={})
    app.register_service_runner = lambda name, runner: app.service_runners.setdefault(name, runner)

    callback(app)
    finalize._finalize_callbacks.clear()


def test_service_exceptions_capture_context(monkeypatch):
    ident = Identity(domain=SERVICES_DOMAIN, namespace="tests", group="echo", name="svc")
    codec_err = ServiceCodecResolutionError(ident=ident, codec="json", service="Demo")
    assert "service codec" in str(codec_err).lower()

    codec_err_default = ServiceCodecResolutionError(ident=None, codec=None, service="Demo")
    assert codec_err_default.codec is None

    monkeypatch.setattr(Identity, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fail")))
    codec_err_failure = ServiceCodecResolutionError(ident=ident, codec="txt", service="Demo")
    assert codec_err_failure.identity is None

    missing = MissingRequiredContextKeys(
        service="Demo", required_keys=["a", "b"], missing_keys=["b"], context_keys=["a"]
    )
    assert "Missing required" in str(missing)
    assert missing.missing_keys == ("b",)

    assert str(ServiceBuildRequestError("bad request"))
    assert str(ServiceStreamError("stream fail"))
    assert str(ServiceDispatchError("dispatch fail"))
    assert str(ServiceDiscoveryError("discovery fail"))
