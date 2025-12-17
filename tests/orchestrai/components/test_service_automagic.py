import pytest

import asyncio

from orchestrai.components.promptkit import PromptSection
from orchestrai.components.codecs import BaseCodec
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.components.services.service import BaseService
from orchestrai.decorators import prompt_section, schema
from orchestrai.registry.singletons import prompt_sections as prompt_registry
from orchestrai.registry.singletons import schemas as schema_registry
from orchestrai.identity import Identity
from orchestrai.identity.domains import CODECS_DOMAIN, SERVICES_DOMAIN


@pytest.fixture(autouse=True)
def _reset_registries():
    prompt_registry._store.clear()
    schema_registry._store.clear()
    prompt_registry.register(AutoPromptSection)
    schema_registry.register(AutoSchema)
    AutomagicService.pin_identity(
        Identity(domain=SERVICES_DOMAIN, namespace="auto", group="service", name="match")
    )
    NoPromptService.pin_identity(
        Identity(domain=SERVICES_DOMAIN, namespace="auto", group="service", name="nomatch")
    )
    yield
    prompt_registry._store.clear()
    schema_registry._store.clear()


@prompt_section(namespace="auto", group="service", name="match")
class AutoPromptSection(PromptSection):
    instruction = "automagic"


@schema(namespace="auto", group="service", name="match")
class AutoSchema(BaseOutputSchema):
    foo: str | None = None


class AutomagicService(BaseService):
    namespace = "auto"
    kind = "service"
    name = "match"
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace=namespace, group=kind, name=name)


class NoPromptService(BaseService):
    namespace = "auto"
    kind = "service"
    name = "nomatch"
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace=namespace, group=kind, name=name)


def test_prompt_plan_automagic_match():
    svc = AutomagicService()
    prompt = asyncio.run(svc.aget_prompt())

    assert svc.context.get("prompt.plan.source") == "automagic"
    assert prompt.instruction == "automagic"


def test_prompt_plan_missing_allows_empty_prompt():
    svc = NoPromptService()
    prompt = asyncio.run(svc.aget_prompt())

    assert svc.context.get("prompt.plan.source") == "none"
    assert prompt.instruction == ""


def test_schema_automagic_match():
    svc = AutomagicService()
    assert svc.response_schema is AutoSchema
    assert svc.context.get("service.response_schema.source") == "identity"


def test_schema_precedence_override_vs_class_vs_codec(monkeypatch):
    @schema(namespace="auto", group="service", name="override")
    class OverrideSchema(BaseOutputSchema):
        bar: str | None = None

    @schema(namespace="auto", group="service", name="codec")
    class CodecSchema(BaseOutputSchema):
        baz: str | None = None

    class CodecWithSchema(BaseCodec):
        response_schema = CodecSchema
        identity = Identity(domain=CODECS_DOMAIN, namespace="auto", group="codec", name="json")

    class ClassSchemaService(AutomagicService):
        response_schema = AutoSchema

    svc_override = AutomagicService(response_schema=OverrideSchema)
    assert svc_override.response_schema is OverrideSchema

    svc_class = ClassSchemaService()
    assert svc_class.response_schema is AutoSchema

    svc_codec = AutomagicService(codec_cls=CodecWithSchema)
    assert svc_codec.response_schema is CodecSchema

    svc_identity = AutomagicService()
    assert svc_identity.response_schema is AutoSchema

    svc_none = NoPromptService()
    assert svc_none.response_schema is None
