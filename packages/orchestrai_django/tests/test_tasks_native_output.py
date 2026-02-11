import types

from orchestrai_django import tasks


class DummyAttempt:
    def __init__(self):
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
        self.openai_response_id = None
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


class FakeRunResult:
    def __init__(self):
        self.output = FakeOutput()
        self.run_id = None
        self.provider_meta = {}
        self.request = FakeRequest()

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

    monkeypatch.setattr(tasks, "ensure_service_registry", lambda app=None: DummyRegistry(DummyService))
    monkeypatch.setattr(tasks.ServiceCallModel.objects, "select_for_update", _select_for_update)
    monkeypatch.setattr(tasks, "_inline_persist_service_call", lambda call: None)

    result = tasks.run_service_call(call.id)

    assert result["status"] == "completed"
    assert call.mark_attempt_args[1] == {"answer": "ok"}
    assert call.schema_fqn == "tests.schema.FakeSchema"
    assert any("schema_fqn" in fields for fields in call.saved_fields if fields)


def test_inline_persist_uses_output_data_even_if_empty(monkeypatch):
    calls = {}

    class DummySchema:
        @classmethod
        def model_validate(cls, data):
            calls["validated"] = data
            return data

    async def fake_persist_schema(schema, context):
        calls["persisted"] = True
        return object()

    def fake_resolve_schema_class(_):
        return DummySchema

    class DummyCallForPersist:
        def __init__(self):
            self.id = "call-2"
            self.schema_fqn = "tests.schema.DummySchema"
            self.output_data = {}
            self.context = {}
            self.correlation_id = None
            self.domain_persisted = False

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
    assert call.domain_persisted is True
