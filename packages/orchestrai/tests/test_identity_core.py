import pytest

from orchestrai.components.codecs import BaseCodec
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.components.services.service import BaseService
from orchestrai.decorators.components.codec_decorator import CodecDecorator
from orchestrai.decorators.components.instruction_decorator import InstructionDecorator
from orchestrai.decorators.components.schema_decorator import SchemaDecorator
from orchestrai.decorators.components.service_decorator import ServiceDecorator
from orchestrai.identity import Identity, IdentityResolver
from orchestrai.identity.domains import (
    CODECS_DOMAIN,
    INSTRUCTIONS_DOMAIN,
    SERVICES_DOMAIN,
    normalize_domain,
)
from orchestrai.instructions import BaseInstruction
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
        ("CODECS", "AttrDomain", "codecs", "arg"),
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
    assert normalize_domain("instructions") == "instructions"
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

    class NoopInstructionDecorator(InstructionDecorator):
        def register(self, candidate):  # type: ignore[override]
            return None

    @NoopServiceDecorator()(namespace="demo", group="svc", name="svc")
    class DemoService(BaseService):
        abstract = False

    @NoopCodecDecorator()(namespace="demo", group="codec", name="json")
    class DemoCodec(BaseCodec):
        abstract = False

    @NoopSchemaDecorator()(namespace="demo", group="schema", name="out")
    class DemoSchema(BaseOutputSchema):
        val: str

    @NoopInstructionDecorator()(namespace="demo", group="instruction", name="section")
    class DemoInstruction(BaseInstruction):
        abstract = False
        instruction = "hi"

    assert DemoService.identity.as_str == "services.demo.svc.svc"
    assert DemoInstruction.identity.as_str == "instructions.demo.instruction.section"
    # Compatibility shims (BaseCodec/BaseOutputSchema) intentionally
    # don't expose identity descriptors anymore.
    assert DemoCodec.__name__ == "DemoCodec"
    assert DemoSchema.__name__ == "DemoSchema"
