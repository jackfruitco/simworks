import types

from orchestrai_django import tasks
from orchestrai_django.signals import ai_response_failed, service_call_succeeded


class DummyAttempt:
    def __init__(self):
        self.id = "attempt-1"
        self.attempt = 1
        self.status = None
        self.response_raw = None
        self.response_provider_raw = None
        self.provider_response_id = None
        self.finish_reason = None
        self.received_at = None
        self.structured_data = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.reasoning_tokens = 0
        self.saved_fields = []

    def mark_dispatched(self):
        self.status = "dispatched"

    def save(self, update_fields=None):
        self.saved_fields.append(update_fields)


class DummyAttempts:
    @staticmethod
    def count():
        return 0

    def filter(self, **kwargs):
        return self

    @staticmethod
    def first():
        return None


class DummyCall:
    def __init__(self):
        self.id = "call-1"
        self.pk = self.id
        self.service_identity = "services.test.native.output"
        self.service_kwargs = {}
        self.status = "pending"
        self.input = {}
        self.context = {}
        self.output_data = None
        self.error = None
        self.dispatch = {}
        self.request = None
        self.backend = "immediate"
        self.queue = None
        self.task_id = None
        self.created_at = None
        self.started_at = None
        self.finished_at = None
        self.related_object_id = None
        self.correlation_id = None
        self.schema_fqn = None
        self.domain_persisted = False
        self.domain_persist_error = None
        self.domain_persist_attempts = 0
        self.successful_attempt = None
        self.provider_response_id = None
        self.provider_previous_response_id = None
        self.messages_json = []
        self.usage_json = None
        self.model_name = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.attempts = DummyAttempts()
        self.saved_fields = []
        self.mark_attempt_args = None

    def allocate_attempt(self):
        return DummyAttempt()

    def to_jsonable(self):
        return {"id": self.id, "status": self.status}

    def save(self, update_fields=None):
        self.saved_fields.append(update_fields)

    def refresh_from_db(self):
        return None

    def mark_attempt_successful(self, attempt, output_data, provider_response_id=None):
        self.mark_attempt_args = (attempt, output_data, provider_response_id)
        self.output_data = output_data
        self.provider_response_id = provider_response_id
        self.status = "completed"


class DummyRegistry:
    def __init__(self, service_cls):
        self._service_cls = service_cls

    def get(self, ident):
        return self._service_cls


class FakeOutput:
    def model_dump(self, mode="json"):
        return {"answer": "ok"}


class FakeSchema:
    __module__ = "tests.schema"


class FakeSchemaWrapper:
    def __init__(self, inner_type):
        self.inner_type = inner_type


class FakeRequest:
    response_schema = FakeSchemaWrapper(FakeSchema)
    model = "fake-model"

    def model_dump(self, mode="json"):
        return {
            "model": self.model,
            "input": [],
            "tools": [],
        }


class FakeResponse:
    provider_response_id = "resp-123"


class FakeRunResult:
    def __init__(self):
        self.output = FakeOutput()
        self.run_id = None
        self.provider_meta = {}
        self.request = FakeRequest()
        self.response = FakeResponse()

    def all_messages_json(self):
        return []

    def timestamp(self):
        return None

    def usage(self):
        return None


def test_resolve_response_schema_unwraps_inner_type():
    assert tasks._resolve_response_schema(FakeSchemaWrapper(FakeSchema)) is FakeSchema


def test_run_service_call_stores_output_and_schema(monkeypatch):
    call = DummyCall()

    class DummyService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def arun(self, **payload):
            return FakeRunResult()

    def _select_for_update(*args, **kwargs):
        return types.SimpleNamespace(get=lambda **kw: call)

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        tasks, "ensure_service_registry", lambda app=None: DummyRegistry(DummyService)
    )
    monkeypatch.setattr(tasks.ServiceCallModel.objects, "select_for_update", _select_for_update)
    monkeypatch.setattr(tasks.transaction, "atomic", lambda: _NoopAtomic())
    monkeypatch.setattr(
        tasks,
        "_inline_persist_service_call",
        lambda call: setattr(call, "domain_persisted", True),
    )

    result = tasks.run_service_call(call.id)

    assert result["status"] == "completed"
    assert call.mark_attempt_args[1] == {"answer": "ok"}
    assert call.mark_attempt_args[2] == "resp-123"
    assert call.schema_fqn == "tests.schema.FakeSchema"
    assert any("schema_fqn" in fields for fields in call.saved_fields if fields)


def test_run_service_call_emits_generic_success_signal(monkeypatch):
    call = DummyCall()
    received: list[dict] = []

    class DummyService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def arun(self, **payload):
            return FakeRunResult()

    def _select_for_update(*args, **kwargs):
        return types.SimpleNamespace(get=lambda **kw: call)

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _receiver(sender, **payload):
        received.append(payload)

    service_call_succeeded.connect(_receiver)
    try:
        monkeypatch.setattr(
            tasks, "ensure_service_registry", lambda app=None: DummyRegistry(DummyService)
        )
        monkeypatch.setattr(tasks.ServiceCallModel.objects, "select_for_update", _select_for_update)
        monkeypatch.setattr(tasks.transaction, "atomic", lambda: _NoopAtomic())
        monkeypatch.setattr(
            tasks,
            "_inline_persist_service_call",
            lambda call: setattr(call, "domain_persisted", True),
        )

        result = tasks.run_service_call(call.id)

        assert result["status"] == "completed"
        assert received == [
            {
                "signal": service_call_succeeded,
                "call": call,
                "call_id": call.id,
                "attempt": 1,
                "service_identity": call.service_identity,
                "provider_response_id": "resp-123",
                "output_data": {"answer": "ok"},
                "context": {"_service_call_attempt_id": "attempt-1"},
            }
        ]
    finally:
        service_call_succeeded.disconnect(_receiver)


def test_run_service_call_defers_generic_success_signal_until_persistence(monkeypatch):
    call = DummyCall()
    received: list[dict] = []

    class DummyService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def arun(self, **payload):
            return FakeRunResult()

    def _select_for_update(*args, **kwargs):
        return types.SimpleNamespace(get=lambda **kw: call)

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _receiver(sender, **payload):
        received.append(payload)

    service_call_succeeded.connect(_receiver)
    try:
        monkeypatch.setattr(
            tasks, "ensure_service_registry", lambda app=None: DummyRegistry(DummyService)
        )
        monkeypatch.setattr(tasks.ServiceCallModel.objects, "select_for_update", _select_for_update)
        monkeypatch.setattr(tasks.transaction, "atomic", lambda: _NoopAtomic())
        monkeypatch.setattr(tasks, "_inline_persist_service_call", lambda call: None)

        result = tasks.run_service_call(call.id)

        assert result["status"] == "completed"
        assert received == []
    finally:
        service_call_succeeded.disconnect(_receiver)


def test_run_service_call_emits_generic_dispatch_signal(monkeypatch):
    call = DummyCall()
    call.context = {
        "simulation_id": 77,
        "correlation_id": "corr-77",
        "user_msg": 42,
    }

    class DummyService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def arun(self, **payload):
            return FakeRunResult()

    dispatched = []

    def _capture_dispatch(emit_call, *, attempt):
        dispatched.append((emit_call, attempt))

    def _select_for_update(*args, **kwargs):
        return types.SimpleNamespace(get=lambda **kw: call)

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        tasks, "ensure_service_registry", lambda app=None: DummyRegistry(DummyService)
    )
    monkeypatch.setattr(tasks.ServiceCallModel.objects, "select_for_update", _select_for_update)
    monkeypatch.setattr(tasks.transaction, "atomic", lambda: _NoopAtomic())
    monkeypatch.setattr(
        tasks,
        "_inline_persist_service_call",
        lambda call: setattr(call, "domain_persisted", True),
    )
    monkeypatch.setattr(tasks, "emit_service_call_dispatched", _capture_dispatch)

    tasks.run_service_call(call.id)

    assert dispatched == [(call, 1)]


def test_inline_persist_uses_output_data_even_if_empty(monkeypatch):
    calls = {}

    class DummySchema:
        @classmethod
        def model_validate(cls, data):
            calls["validated"] = data
            return data

    async def fake_persist_schema(schema, context):
        calls["persisted"] = True
        calls["persist_context"] = context
        return object()

    def fake_resolve_schema_class(_):
        return DummySchema

    class DummyCallForPersist:
        def __init__(self):
            self.id = "call-2"
            self.schema_fqn = "tests.schema.DummySchema"
            self.output_data = {}
            self.context = {
                "simulation_id": 123,
                "conversation_id": 456,
                "_service_call_attempt_id": "attempt-1",
            }
            self.correlation_id = None
            self.domain_persisted = False
            self.provider_response_id = None
            self.previous_provider_response_id = None

        def save(self, update_fields=None):
            self.saved_fields = update_fields

    call = DummyCallForPersist()

    monkeypatch.setattr(
        "orchestrai_django.persistence.resolve_schema_class",
        fake_resolve_schema_class,
    )
    monkeypatch.setattr(
        "orchestrai_django.persistence.persist_schema",
        fake_persist_schema,
    )

    tasks._inline_persist_service_call(call)

    assert calls.get("validated") == {}
    assert calls.get("persisted") is True
    assert calls["persist_context"].simulation_id == 123
    assert calls["persist_context"].extra["conversation_id"] == 456
    assert calls["persist_context"].extra["service_call_attempt_id"] == "attempt-1"
    assert call.domain_persisted is True


def test_process_pending_persistence_emits_generic_success_signal_after_persist(monkeypatch):
    call = DummyCall()
    call.status = "completed"
    call.schema_fqn = "tests.schema.FakeSchema"
    call.domain_persisted = False
    call.domain_persist_attempts = 0

    received: list[dict] = []

    class PendingQuery:
        def __init__(self, items):
            self._items = items

        def exclude(self, **kwargs):
            return self

        def select_for_update(self, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def __getitem__(self, item):
            return self._items

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _receiver(sender, **payload):
        received.append(payload)

    service_call_succeeded.connect(_receiver)
    try:
        monkeypatch.setattr(
            tasks.ServiceCallModel.objects,
            "filter",
            lambda **kwargs: PendingQuery([call]),
        )
        monkeypatch.setattr(tasks.ServiceCallModel.objects, "bulk_update", lambda calls, fields: None)
        monkeypatch.setattr(tasks.transaction, "atomic", lambda: _NoopAtomic())
        monkeypatch.setattr(
            tasks,
            "_inline_persist_service_call",
            lambda pending_call: setattr(pending_call, "domain_persisted", True),
        )

        stats = tasks.process_pending_persistence.call()

        assert stats["processed"] == 1
        assert received == [
            {
                "signal": service_call_succeeded,
                "call": call,
                "call_id": call.id,
                "attempt": None,
                "service_identity": call.service_identity,
                "provider_response_id": None,
                "output_data": None,
                "context": {},
            }
        ]
    finally:
        service_call_succeeded.disconnect(_receiver)


def test_run_service_call_retry_does_not_emit_non_terminal_failure_signal(monkeypatch):
    class RetryAttempt:
        def __init__(self):
            self.attempt = 1
            self.is_retryable = True
            self.marked_error = None

        def mark_dispatched(self):
            return None

        def mark_error(self, error, is_retryable=True):
            self.marked_error = error
            self.is_retryable = is_retryable

    class RetryAttempts:
        @staticmethod
        def count():
            return 0

        def filter(self, **kwargs):
            return self

        @staticmethod
        def first():
            return None

    class RetryCall(DummyCall):
        def __init__(self):
            super().__init__()
            self.context = {"simulation_id": 7, "user_msg": 11}
            self.attempts = RetryAttempts()
            self._attempt = RetryAttempt()

        def allocate_attempt(self):
            return self._attempt

    class NoisyFailingService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.emitter = types.SimpleNamespace(
                emit_failure=lambda *args, **kwargs: ai_response_failed.send(
                    sender=self.__class__,
                    error="attempt-level failure",
                    context={"simulation_id": 7, "user_msg": 11},
                )
            )

        async def arun(self, **payload):
            # Simulate a transient failure; run_service_call should retry.
            self.emitter.emit_failure(
                {}, "services.test.native.output", None, "temporarily unavailable"
            )
            raise RuntimeError("temporarily unavailable")

    call = RetryCall()
    enqueued_retry_call_ids = []
    observed_failures = []

    def _select_for_update(*args, **kwargs):
        return types.SimpleNamespace(get=lambda **kw: call)

    def _capture_failure(sender, **kwargs):
        observed_failures.append(kwargs)

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    ai_response_failed.connect(_capture_failure, weak=False)
    try:
        monkeypatch.setattr(
            tasks, "ensure_service_registry", lambda app=None: DummyRegistry(NoisyFailingService)
        )
        monkeypatch.setattr(tasks.ServiceCallModel.objects, "select_for_update", _select_for_update)
        monkeypatch.setattr(tasks.transaction, "atomic", lambda: _NoopAtomic())
        monkeypatch.setattr(
            tasks,
            "run_service_call_task",
            types.SimpleNamespace(enqueue=lambda call_id: enqueued_retry_call_ids.append(call_id)),
        )

        result = tasks.run_service_call(call.id)
    finally:
        ai_response_failed.disconnect(_capture_failure)

    assert result["status"] == "in_progress"
    assert enqueued_retry_call_ids == [call.id]
    # No failure signal should be emitted until retries are exhausted.
    assert observed_failures == []


def test_run_service_call_skips_when_in_flight_attempt_exists(monkeypatch):
    """Duplicate task dispatch is silently skipped when another attempt is already in-flight."""
    from django.utils import timezone

    class InFlightAttempt:
        attempt = 1
        status = "dispatched"
        updated_at = timezone.now()  # Fresh — not stale

    class InFlightAttempts:
        @staticmethod
        def count():
            return 1

        def filter(self, **kwargs):
            return self

        @staticmethod
        def first():
            return InFlightAttempt()

    class InFlightCall(DummyCall):
        def __init__(self):
            super().__init__()
            self.status = "in_progress"
            self.attempts = InFlightAttempts()
            self._allocate_called = False

        def allocate_attempt(self):
            self._allocate_called = True
            return DummyAttempt()

    call = InFlightCall()
    service_executed = []

    class NeverCalledService:
        def __init__(self, **kwargs):
            pass

        async def arun(self, **payload):
            service_executed.append(True)
            return FakeRunResult()

    def _select_for_update(*args, **kwargs):
        return types.SimpleNamespace(get=lambda **kw: call)

    class _NoopAtomic:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        tasks, "ensure_service_registry", lambda app=None: DummyRegistry(NeverCalledService)
    )
    monkeypatch.setattr(tasks.ServiceCallModel.objects, "select_for_update", _select_for_update)
    monkeypatch.setattr(tasks.transaction, "atomic", lambda: _NoopAtomic())

    result = tasks.run_service_call(call.id)

    assert result["status"] == "in_progress"
    assert not call._allocate_called, "allocate_attempt must not be called when in-flight"
    assert not service_executed, "LLM service must not be executed when in-flight"
