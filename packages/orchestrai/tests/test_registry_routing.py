from orchestrai.identity import Identity
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN, SERVICES_DOMAIN
from orchestrai.instructions import BaseInstruction
from orchestrai.registry import ComponentStore
from orchestrai.registry.active_app import get_registry_for, push_active_registry_app
from orchestrai.registry.records import RegistrationRecord


class DemoInstruction(BaseInstruction):
    abstract = False
    namespace = "demo"
    group = "instruction"
    name = "section"
    instruction = "demo"


def test_get_registry_for_instructions_prefers_instruction_domain():
    store = ComponentStore()
    app = type("App", (), {"component_store": store})()

    with push_active_registry_app(app):
        registry = get_registry_for(BaseInstruction)

    assert registry is store.registry(INSTRUCTIONS_DOMAIN)
    assert store.domains() == (INSTRUCTIONS_DOMAIN,)


def test_instruction_get_uses_instruction_registry():
    store = ComponentStore()
    store.register(RegistrationRecord(component=DemoInstruction, identity=DemoInstruction.identity))
    app = type("App", (), {"component_store": store})()

    with push_active_registry_app(app):
        resolved = store.get(INSTRUCTIONS_DOMAIN, DemoInstruction.identity)

    assert resolved is DemoInstruction
    assert INSTRUCTIONS_DOMAIN in store.domains()
    assert SERVICES_DOMAIN not in store.domains()


def test_instruction_identity_resolver_prefers_instruction_domain():
    store = ComponentStore()
    store.register(RegistrationRecord(component=DemoInstruction, identity=DemoInstruction.identity))
    app = type("App", (), {"component_store": store})()

    with push_active_registry_app(app):
        resolved = Identity.resolve.try_for_(BaseInstruction, DemoInstruction.identity.as_str)

    assert resolved is DemoInstruction
    assert store.domains() == (INSTRUCTIONS_DOMAIN,)
