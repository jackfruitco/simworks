import asyncio
import sys

import pytest

from orchestrai import OrchestrAI, current_app
from orchestrai.identity import Identity
from orchestrai.components.codecs.codec import BaseCodec
from orchestrai.components.promptkit import PromptPlan, PromptSection
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.components.services.service import BaseService
from orchestrai.decorators import codec, prompt_section, schema, service
from orchestrai.registry.singletons import codecs as codec_registry
from orchestrai.registry.singletons import prompt_sections as prompt_section_registry
from orchestrai.registry.singletons import schemas as schema_registry
from orchestrai.registry.singletons import services as service_registry
from orchestrai.shared import shared_service
from orchestrai.types import Request, Response


# ----------------------------- helpers -----------------------------


class RecordingEmitter:
    def __init__(self):
        self.requests = []
        self.responses = []
        self.failures = []
        self.stream_chunks = []
        self.stream_complete = []

    def emit_request(self, context, namespace, request_dto):
        self.requests.append((namespace, request_dto))

    def emit_response(self, context, namespace, response_dto):
        self.responses.append((namespace, response_dto))

    def emit_failure(self, context, namespace, correlation_id, error):
        self.failures.append((namespace, correlation_id, error))

    def emit_stream_chunk(self, context, namespace, chunk_dto):
        self.stream_chunks.append((namespace, chunk_dto))

    def emit_stream_complete(self, context, namespace, correlation_id):
        self.stream_complete.append((namespace, correlation_id))


class RecordingClient:
    def __init__(self, *, response_payload: str = "ok"):
        self.name = "recording"
        self.response_payload = response_payload
        self.sent_requests: list[Request] = []

    async def send_request(self, req: Request) -> Response:
        self.sent_requests.append(req)
        return Response(output=[], request=req)

    async def stream_request(self, req: Request):  # pragma: no cover - stream path exercised separately
        self.sent_requests.append(req)
        yield {"stream": True}


@schema(namespace="svc", kind="result", name="explicit")
class ExplicitSchema(BaseOutputSchema):
    foo: str | None = None


@schema(namespace="svc", kind="service", name="identity")
class IdentitySchema(BaseOutputSchema):
    bar: str | None = None


@codec(namespace="fake", kind="responses", name="json")
class RegistryCodec(BaseCodec):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encoded: Request | None = None
        self.decoded: Response | None = None

    async def aencode(self, req: Request) -> None:
        self.encoded = req
        await super().aencode(req)

    async def adecode(self, resp: Response):
        self.decoded = resp
        return resp


class InlineCodec(BaseCodec):
    identity = Identity("svc", "codec", "inline")
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encoded: Request | None = None
        self.decoded: Response | None = None

    async def aencode(self, req: Request) -> None:
        self.encoded = req
        await super().aencode(req)

    async def adecode(self, resp: Response):
        self.decoded = resp
        return resp


@prompt_section(namespace="svc", kind="section", name="base")
class IdentitySection(PromptSection):
    identity = Identity("svc", "section", "base")
    instruction = "identity instruction"
    message = "identity message"


class OverrideSection(PromptSection):
    namespace = "svc"
    kind = "section"
    name = "override"
    identity = Identity(namespace, kind, name)
    instruction = "override instruction"
    message = "override message"


class SimpleService(BaseService):
    namespace = "svc"
    kind = "service"
    name = "base"
    provider_name = "fake"
    abstract = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prepared_with_codec: BaseCodec | None = None

    async def on_success(self, context: dict, resp: Response) -> None:
        context["on_success_called"] = True


# ----------------------------- fixtures -----------------------------


@pytest.fixture(autouse=True)
def _reset_registries():
    # ensure test isolation for identity registries
    codec_registry._store.clear()
    schema_registry._store.clear()
    prompt_section_registry._store.clear()
    service_registry._store.clear()
    # re-register decorated components needed for identity-based resolution
    codec_registry.register(RegistryCodec)
    schema_registry.register(ExplicitSchema)
    schema_registry.register(IdentitySchema)
    prompt_section_registry.register(IdentitySection)
    SimpleService.pin_identity(Identity("svc", "service", "base"), {})
    yield
    codec_registry._store.clear()
    schema_registry._store.clear()
    prompt_section_registry._store.clear()
    service_registry._store.clear()


@pytest.fixture()
def emitter():
    return RecordingEmitter()


@pytest.fixture()
def client():
    return RecordingClient()


# ----------------------------- definition & registration -----------------------------


def test_service_definition_methods_register_and_pin_identity():
    @service(namespace="svc", kind="service", name="decorated")
    class DecoratedService(SimpleService):
        pass

    assert DecoratedService.identity.as_str == "svc.service.decorated"
    assert service_registry.get("svc.service.decorated") is DecoratedService

    inline = SimpleService()
    assert inline.identity.as_str == "svc.service.base"

    built = DecoratedService.using()
    assert isinstance(built, DecoratedService)


def test_shared_service_registration_via_finalize(tmp_path):
    mod = tmp_path / "shared_mod.py"
    mod.write_text(
        "from orchestrai.shared import shared_service\n"\
        "@shared_service()\n"
        "def dyn():\n"
        "    return 'ok'\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        app = OrchestrAI("shared")
        app.conf.update_from_mapping({"DISCOVERY_PATHS": ["shared_mod"]})
        app.start()
        assert app.services.get("dyn")() == "ok"
    finally:
        sys.path.remove(str(tmp_path))
        if "shared_mod" in sys.modules:
            sys.modules.pop("shared_mod")


# ----------------------------- resolution -----------------------------


def test_current_app_resolution_isolated_between_apps():
    app_a = OrchestrAI("a")
    app_b = OrchestrAI("b")
    app_a.services.register("svc", "A")
    app_b.services.register("svc", "B")

    with app_a.as_current():
        assert current_app.services.get("svc") == "A"
    with app_b.as_current():
        assert current_app.services.get("svc") == "B"


# ----------------------------- schema precedence -----------------------------


def test_response_schema_precedence_override_class_identity(emitter, client):
    class ClassSchema(BaseOutputSchema):
        val: str | None = None

    @schema(namespace="svc", kind="service", name="identity_match")
    class IdentityResolved(BaseOutputSchema):
        data: str | None = None
    IdentityResolved.pin_identity(Identity("svc", "service", "identity_match"), {})
    schema_registry.register(IdentityResolved)
    assert schema_registry.get(Identity("svc", "service", "identity_match")) is IdentityResolved

    class SchemaService(SimpleService):
        response_schema = ClassSchema
    SchemaService.pin_identity(Identity("svc", "service", "schema"), {})

    # override wins
    svc_override = SchemaService(
        emitter=emitter,
        client=client,
        response_schema=ExplicitSchema,
        prompt_instruction_override="inst",
        prompt_message_override="msg",
    )
    svc_override.execute()
    assert svc_override.response_schema is ExplicitSchema

    # class default when no override
    svc_class = SchemaService(
        emitter=emitter,
        client=client,
        prompt_instruction_override="inst",
        prompt_message_override="msg",
    )
    svc_class.execute()
    assert svc_class.response_schema is ClassSchema

    # identity lookup when no class/override
    class IdentityService(SimpleService):
        pass
    IdentityService.pin_identity(Identity("svc", "service", "identity_match"), {})

    svc_identity = IdentityService(
        emitter=emitter,
        client=client,
        prompt_instruction_override="inst",
        prompt_message_override="msg",
    )
    svc_identity.execute()
    assert svc_identity.response_schema is IdentityResolved


# ----------------------------- codec precedence -----------------------------


def test_codec_precedence_override_then_class_then_registry(emitter, client):
    class ClassCodec(BaseCodec):
        identity = Identity("svc", "codec", "class")

    class CodecService(SimpleService):
        codec_cls = ClassCodec
        response_schema = ExplicitSchema
    CodecService.pin_identity(Identity("svc", "service", "codec"), {})

    # override wins over class
    svc_override = CodecService(
        emitter=emitter,
        client=client,
        codec=InlineCodec,
        prompt_instruction_override="inst",
        prompt_message_override="msg",
    )
    svc_override.execute()
    codec_cls, _ = svc_override._select_codec_class()
    assert codec_cls is InlineCodec

    # class-level codec when no override
    svc_class = CodecService(
        emitter=emitter,
        client=client,
        prompt_instruction_override="inst",
        prompt_message_override="msg",
    )
    svc_class.execute()
    codec_cls, _ = svc_class._select_codec_class()
    assert codec_cls is ClassCodec

    # registry-based selection when no override/class
    svc_registry = SimpleService(
        emitter=emitter,
        client=client,
        response_schema=ExplicitSchema,
        prompt_instruction_override="inst",
        prompt_message_override="msg",
    )
    codec_cls, _ = svc_registry._select_codec_class()
    assert codec_cls is RegistryCodec


# ----------------------------- prompt selection -----------------------------


def test_prompt_plan_precedence(emitter, client):
    class PlanService(SimpleService):
        prompt_plan = PromptPlan.from_sections([IdentitySection])
    PlanService.pin_identity(Identity("svc", "service", "plan"), {})

    svc_class = PlanService(emitter=emitter, client=client)
    prompt_class = asyncio.run(svc_class.aget_prompt())
    assert prompt_class.instruction == IdentitySection.instruction

    override_plan = PromptPlan.from_sections([OverrideSection])
    svc_override = PlanService(emitter=emitter, client=client, prompt_plan=override_plan)
    prompt_override = asyncio.run(svc_override.aget_prompt())
    assert prompt_override.instruction == OverrideSection.instruction

    class MatchingSection(PromptSection):
        identity = Identity("svc", "service", "base")
        instruction = "identity instruction"
        message = "identity message"

    prompt_section_registry.register(MatchingSection)

    svc_identity = SimpleService(emitter=emitter, client=client)
    prompt_identity = asyncio.run(svc_identity.aget_prompt())
    assert prompt_identity.instruction == MatchingSection.instruction


# ----------------------------- execution pipeline -----------------------------


def test_execute_runs_full_pipeline_with_schema_codec_sections(emitter, client):
    svc = SimpleService(
        emitter=emitter,
        client=client,
        response_schema=ExplicitSchema,
        codec=RegistryCodec,
        prompt_plan=PromptPlan.from_sections([IdentitySection]),
    )
    resp = svc.execute()

    assert isinstance(resp, Response)
    # codec applied schema hint
    assert emitter.responses, "emitter should capture response"
    request = client.sent_requests[0]
    assert request.response_schema is ExplicitSchema
    assert request.provider_response_format is not None


def test_execute_without_codec_or_schema(emitter, client):
    svc = SimpleService(
        emitter=emitter,
        client=client,
        prompt_instruction_override="hi",
        prompt_message_override="there",
    )
    resp = svc.execute()
    assert isinstance(resp, Response)
    request = client.sent_requests[0]
    assert request.response_schema is None


def test_emitter_required_error(client):
    svc = SimpleService(client=client, prompt_instruction_override="hi", prompt_message_override="there")
    with pytest.raises(Exception):
        svc.execute()


def test_retry_propagates_codec_errors(emitter, client):
    class ErrorCodec(BaseCodec):
        async def aencode(self, req: Request) -> None:
            raise RuntimeError("boom")

    svc = SimpleService(
        emitter=emitter,
        client=client,
        response_schema=ExplicitSchema,
        codec=ErrorCodec,
        prompt_instruction_override="inst",
        prompt_message_override="msg",
    )

    with pytest.raises(Exception):
        svc.execute()


def test_streaming_path_emits_chunks(emitter, client):
    svc = SimpleService(
        emitter=emitter,
        client=client,
        prompt_instruction_override="inst",
        prompt_message_override="msg",
    )
    asyncio.run(svc.run_stream())
    assert emitter.stream_complete, "stream completion should be emitted"

