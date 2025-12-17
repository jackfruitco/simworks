import pytest
from typing import ClassVar

from orchestrai.components.codecs import BaseCodec
from orchestrai.components.promptkit import PromptPlan, PromptSection
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.contrib.provider_backends.openai.schema_adapters import OpenaiWrapper
from orchestrai.identity import Identity
from orchestrai.registry import ComponentStore
from orchestrai.registry.records import RegistrationRecord
from orchestrai.registry.active_app import set_active_registry_app
from orchestrai.resolve import resolve_codec, resolve_prompt_plan, resolve_schema
from orchestrai.components.services.service import BaseService


DOMAIN = "demo"


class DemoSchema(BaseOutputSchema):
    identity: ClassVar[Identity] = Identity(domain=DOMAIN, namespace="demo", group="schema", name="svc")
    foo: str


class DemoPrompt(PromptSection):
    abstract = False
    identity: ClassVar[Identity] = Identity(domain=DOMAIN, namespace="demo", group="prompt_section", name="svc")
    instruction = "hello"
    message = "world"


class AltPrompt(PromptSection):
    abstract = False
    identity: ClassVar[Identity] = Identity(domain=DOMAIN, namespace="demo", group="prompt_section", name="alt")
    instruction = "alt"


class LowCodec(BaseCodec):
    abstract = False
    identity: ClassVar[Identity] = Identity(domain=DOMAIN, namespace="demo", group="codec", name="low")
    priority = 1
    response_schema = DemoSchema

    @classmethod
    def matches(cls, *, provider, api, result_type):
        return provider == "demo" and result_type == "json"


class HighCodec(BaseCodec):
    abstract = False
    identity: ClassVar[Identity] = Identity(domain=DOMAIN, namespace="demo", group="codec", name="high")
    priority = 5
    response_schema = DemoSchema

    @classmethod
    def matches(cls, *, provider, api, result_type):
        return provider == "demo" and result_type == "json"


class AdapterCodec(BaseCodec):
    abstract = False
    identity: ClassVar[Identity] = Identity(domain=DOMAIN, namespace="demo", group="codec", name="adapter")
    response_schema = DemoSchema
    schema_adapters = (OpenaiWrapper(order=0),)

    @classmethod
    def matches(cls, *, provider, api, result_type):
        return provider == "demo" and result_type == "json"


class DemoService(BaseService):
    abstract = False
    identity: ClassVar[Identity] = Identity(domain=DOMAIN, namespace="demo", group="service", name="svc")
    provider_name = "demo"


@pytest.fixture()
def store():
    return ComponentStore()


def register(store: ComponentStore, component) -> None:
    store.register(RegistrationRecord(component=component, identity=component.identity))


def attach_store(store: ComponentStore) -> None:
    app = type("App", (), {"component_store": store})()
    set_active_registry_app(app)


def test_prompt_plan_resolution_branches(store):
    # explicit
    explicit_plan = PromptPlan.from_sections([DemoPrompt])
    svc_explicit = DemoService(prompt_plan=explicit_plan)
    res_explicit = resolve_prompt_plan(svc_explicit)
    assert res_explicit.branch == "explicit"
    assert res_explicit.value is explicit_plan

    # registry
    register(store, DemoPrompt)
    attach_store(store)
    svc_registry = DemoService()
    res_registry = resolve_prompt_plan(svc_registry)
    assert res_registry.branch == "registry"
    assert isinstance(res_registry.value, PromptPlan)

    # none
    attach_store(ComponentStore())
    svc_none = DemoService()
    res_none = resolve_prompt_plan(svc_none)
    assert res_none.branch == "none"
    assert res_none.value is None


def test_schema_resolution_branches(store):
    ident = Identity(domain=DOMAIN, namespace="demo", group="service", name="svc")

    # override wins
    res_override = resolve_schema(identity=ident, override=DemoSchema, store=store)
    assert res_override.branch == "override"
    assert res_override.value is DemoSchema

    # class default
    res_class = resolve_schema(identity=ident, default=DemoSchema, store=store)
    assert res_class.branch == "class"

    # registry lookup
    register(store, DemoSchema)
    attach_store(store)
    res_registry = resolve_schema(identity=ident, store=store)
    assert res_registry.branch == "registry"
    assert res_registry.value is DemoSchema

    # none branch
    empty = ComponentStore()
    res_none = resolve_schema(identity=ident, store=empty)
    assert res_none.branch == "none"
    assert res_none.value is None


def test_schema_adapter_application():
    ident = Identity(domain=DOMAIN, namespace="demo", group="service", name="svc")
    res = resolve_schema(identity=ident, override=DemoSchema, adapters=AdapterCodec.schema_adapters)
    schema_json = res.selected.meta.get("schema_json")
    assert res.branch == "override"
    assert schema_json is not None
    assert schema_json.get("type") == "json_schema"
    assert "json_schema" in schema_json


def test_codec_resolution_branches(store):
    svc = DemoService()
    attach_store(store)

    res_override = resolve_codec(service=svc, override=HighCodec)
    assert res_override.branch == "override"
    assert res_override.value is HighCodec

    res_explicit = resolve_codec(service=svc, explicit=LowCodec)
    assert res_explicit.branch == "explicit"
    assert res_explicit.value is LowCodec

    register(store, LowCodec)
    register(store, HighCodec)
    constraints = {"provider": "demo", "api": "responses", "result_type": "json"}
    res_candidates = resolve_codec(service=svc, constraints=constraints, store=store)
    assert res_candidates.branch == "candidates"
    assert res_candidates.value is HighCodec
    assert HighCodec in res_candidates.selected.meta.get("candidate_classes", ())

    res_none = resolve_codec(service=svc, store=ComponentStore())
    assert res_none.branch == "none"
    assert res_none.value is None


def test_service_prepare_end_to_end(store):
    register(store, DemoPrompt)
    register(store, DemoSchema)
    register(store, AdapterCodec)

    attach_store(store)
    svc = DemoService()

    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        req, codec, attrs = loop.run_until_complete(svc.aprepare(stream=False))
    finally:
        loop.close()

    assert codec is not None
    assert req.response_schema_json is not None
    assert req.provider_response_format == req.response_schema_json
    assert req.response_schema_json.get("type") == "json_schema"

    # Context should record branches/identities
    assert svc.context.get("schema.branch") == "registry"
    assert "codec.branch" in svc.context
    assert "prompt.plan.branch" in svc.context
    assert attrs["codec"] == svc.context.get("service.codec.label")
