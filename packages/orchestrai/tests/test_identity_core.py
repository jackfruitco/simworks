import pytest

from orchestrai.components.codecs import BaseCodec
from orchestrai.components.promptkit import PromptSection
from orchestrai.components.providerkit import BaseProvider
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.components.services.service import BaseService
from orchestrai.decorators import (
    codec,
    prompt_section,
    provider,
    provider_backend,
    schema,
    service,
)
from orchestrai.decorators.components.codec_decorator import CodecDecorator
from orchestrai.decorators.components.prompt_section_decorator import PromptSectionDecorator
from orchestrai.decorators.components.provider_decorators import (
    ProviderBackendDecorator,
    ProviderDecorator,
)
from orchestrai.decorators.components.schema_decorator import SchemaDecorator
from orchestrai.decorators.components.service_decorator import ServiceDecorator
from orchestrai.identity import Identity, IdentityResolver
from orchestrai.identity.domains import (
    CODECS_DOMAIN,
    PROMPT_SECTIONS_DOMAIN,
    PROVIDER_BACKENDS_DOMAIN,
    PROVIDERS_DOMAIN,
    SCHEMAS_DOMAIN,
    SERVICES_DOMAIN,
    normalize_domain,
)
from orchestrai.registry.base import ComponentRegistry
from orchestrai.registry.exceptions import RegistryCollisionError


def test_domain_precedence_and_normalization_default_context():
    class Demo:
        namespace = "DemoSpace"
        group = "Group"
        name = "ExplicitName"

    ident, meta = IdentityResolver().resolve(Demo, context={"default_domain": " SERVICES "})

    assert ident.domain == SERVICES_DOMAIN
    assert meta["simcore.identity.source.domain"] == "default"
    assert ident.namespace == "demo_space"
    assert ident.group == "group"
    assert ident.name == "ExplicitName"
    assert meta["simcore.tuple4.post_norm"] == ident.as_str


@pytest.mark.parametrize(
    "domain_arg, domain_attr, expected, source",
    [
        ("Provider Backends", "AttrDomain", "provider-backends", "arg"),
        (None, "CODECS", "codecs", "attr"),
    ],
)
def test_domain_arg_overrides_and_attr_precedence(domain_arg, domain_attr, expected, source):
    class Demo:
        domain = domain_attr
        namespace = "demo"
        group = "demo"

    ident, meta = IdentityResolver().resolve(Demo, domain=domain_arg)

    assert ident.domain == expected
    assert meta["simcore.identity.source.domain"] == source


def test_normalize_domain_supported_and_rejected():
    assert normalize_domain("prompt_sections") == "prompt-sections"
    assert normalize_domain("schemas") == "schemas"

    with pytest.raises(ValueError):
        normalize_domain("unknown-domain")

    with pytest.raises(ValueError):
        normalize_domain(None, default=None)


def test_resolve_facade_tuple_helpers_are_four_part_only():
    ident = Identity(domain="d", namespace="n", group="g", name="x")

    assert Identity.resolve.as_tuple(ident) == ("d", "n", "g", "x")
    assert Identity.resolve.as_tuple4(ident) == ("d", "n", "g", "x")
    assert Identity.resolve.as_label(ident) == "d.n.g.x"


def test_registry_collision_is_domain_sensitive_and_mentions_both_classes():
    registry = ComponentRegistry()

    class DemoService:
        identity = Identity(domain=SERVICES_DOMAIN, namespace="demo", group="svc", name="item")

    class DemoCodec:
        identity = Identity(domain=CODECS_DOMAIN, namespace="demo", group="svc", name="item")

    registry.register(DemoService)
    registry.register(DemoCodec)

    class DuplicateService:
        identity = Identity(domain=SERVICES_DOMAIN, namespace="demo", group="svc", name="item")

    with pytest.raises(RegistryCollisionError) as excinfo:
        registry.register(DuplicateService)

    message = str(excinfo.value)
    assert "DemoService" in message
    assert "DuplicateService" in message


def test_decorators_apply_domain_defaults_per_component_type():
    class NoopServiceDecorator(ServiceDecorator):
        def register(self, candidate):  # type: ignore[override]
            return None

    class NoopCodecDecorator(CodecDecorator):
        def register(self, candidate):  # type: ignore[override]
            return None

    class NoopSchemaDecorator(SchemaDecorator):
        def register(self, candidate):  # type: ignore[override]
            return None

    class NoopPromptDecorator(PromptSectionDecorator):
        def register(self, candidate):  # type: ignore[override]
            return None

    class NoopProviderDecorator(ProviderDecorator):
        def register(self, candidate):  # type: ignore[override]
            return None

    class NoopProviderBackendDecorator(ProviderBackendDecorator):
        def register(self, candidate):  # type: ignore[override]
            return None

    @NoopServiceDecorator()(namespace="demo", group="svc", name="svc")
    class DemoService(BaseService):
        abstract = False
        provider_name = "stub"

    @NoopCodecDecorator()(namespace="demo", group="codec", name="json")
    class DemoCodec(BaseCodec):
        abstract = False

    @NoopSchemaDecorator()(namespace="demo", group="schema", name="out")
    class DemoSchema(BaseOutputSchema):
        val: str

    @NoopPromptDecorator()(namespace="demo", group="prompt", name="section")
    class DemoPrompt(PromptSection):
        abstract = False
        instruction = "hi"

    @NoopProviderDecorator()(namespace="demo", group="provider", name="default")
    class DemoProvider(BaseProvider):
        abstract = False

    @NoopProviderBackendDecorator()(namespace="demo", group="backend", name="default")
    class DemoBackend(BaseProvider):
        abstract = False

    assert DemoService.identity.as_str == "services.demo.svc.svc"
    assert DemoCodec.identity.as_str == "codecs.demo.codec.json"
    assert DemoSchema.identity.as_str == "schemas.demo.schema.out"
    assert DemoPrompt.identity.as_str == "prompt-sections.demo.prompt.section"
    assert DemoProvider.identity.as_str == "providers.demo.provider.default"
    assert DemoBackend.identity.as_str == "provider-backends.demo.backend.default"
