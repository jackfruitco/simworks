from types import SimpleNamespace

import pytest

from orchestrai._state import push_current_app
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity
from orchestrai.service_runners import BaseServiceRunner, TaskStatus
from orchestrai.services.call import ServiceCall, _coerce_runner_name


class DemoService(BaseService):
    abstract = False
    identity = Identity(domain="services", namespace="demo", group="svc", name="demo")


class RecordingRunner(BaseServiceRunner):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def start(self, **payload):
        self.calls.append(("start", payload))
        return payload

    def enqueue(self, **payload):
        self.calls.append(("enqueue", payload))
        return TaskStatus(id="task-1", state="queued")


class UnsupportedRunner(BaseServiceRunner):
    def start(self, **payload):
        return payload

    def enqueue(self, **payload):  # pragma: no cover - exercised indirectly
        return payload

    def stream(self, **_payload):
        raise NotImplementedError("streaming not supported")

    def get_status(self, **_payload):
        raise NotImplementedError("status not supported")


class TaskAwareRunner(BaseServiceRunner):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def start(self, **payload):
        self.calls.append(("start", payload))
        return payload

    def enqueue(self, **payload):
        self.calls.append(("enqueue", payload))
        return payload

    def stream(self, **payload):
        self.calls.append(("stream", payload))
        return payload


def test_coerce_runner_name_prefers_explicit_and_identity():
    app = SimpleNamespace(default_service_runner=None)

    assert _coerce_runner_name(app, DemoService, explicit="custom") == "custom"

    class NoIdentity(BaseService):
        abstract = False

    assert _coerce_runner_name(app, NoIdentity, explicit=None) == "no-identity"


def test_service_call_dispatch_merges_kwargs_and_uses_phase():
    runner = RecordingRunner()
    app = SimpleNamespace(service_runners={"demo": runner})

    call = ServiceCall(service_cls=DemoService, service_kwargs={"foo": "bar"})

    with push_current_app(app):
        result = call.start(extra=1)

    assert result["service_kwargs"] == {"foo": "bar", "extra": 1}
    assert result["phase"] == "service"
    assert runner.calls[0][0] == "start"


def test_service_call_raises_for_unsupported_operations():
    runner = UnsupportedRunner()
    app = SimpleNamespace(service_runners={"demo": runner})
    call = ServiceCall(service_cls=DemoService, runner_name=None)

    with push_current_app(app):
        with pytest.raises(NotImplementedError):
            call.stream()
        with pytest.raises(NotImplementedError):
            call.get_status()


def test_service_call_task_property_switches_phase():
    call = ServiceCall(
        service_cls=DemoService,
        service_kwargs={"foo": "bar"},
        runner_name="demo",
        runner_kwargs={"priority": 5},
        phase="service",
    )

    task_call = call.task

    assert task_call is not call
    assert task_call.phase == "runner"
    assert task_call.service_cls is call.service_cls
    assert task_call.service_kwargs == call.service_kwargs
    assert task_call.runner_name == call.runner_name
    assert task_call.runner_kwargs == call.runner_kwargs


def test_service_call_task_supports_enqueue_stream_and_start():
    runner = TaskAwareRunner()
    app = SimpleNamespace(service_runners={"demo": runner})
    call = ServiceCall(
        service_cls=DemoService,
        service_kwargs={"foo": "bar"},
        runner_name="demo",
    )

    with push_current_app(app):
        task_call = call.task
        enqueue_payload = task_call.enqueue(extra=1)
        stream_payload = task_call.stream()
        start_payload = task_call.start()

    assert enqueue_payload["phase"] == "runner"
    assert enqueue_payload["service_kwargs"] == {"foo": "bar", "extra": 1}
    assert stream_payload["phase"] == "runner"
    assert stream_payload["service_kwargs"] == {"foo": "bar"}
    assert start_payload["phase"] == "runner"
    assert start_payload["service_kwargs"] == {"foo": "bar"}

    assert runner.calls == [
        ("enqueue", enqueue_payload),
        ("stream", stream_payload),
        ("start", start_payload),
    ]


def test_service_task_wraps_context_and_runner_phase():
    ctx = {"user": "demo", "nested": {"a": 1}}
    service = DemoService(context=ctx)

    call = service.task

    assert call.service_cls is DemoService
    assert call.phase == "runner"
    assert call.service_kwargs["context"]["user"] == "demo"
    assert call.service_kwargs["context"]["nested"] == {"a": 1}
    assert call.service_kwargs["context"] is not ctx
