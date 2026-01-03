from typing import ClassVar

from orchestrai.components.promptkit import PromptSection
from orchestrai.identity import Identity
from orchestrai.identity.domains import PROMPT_SECTIONS_DOMAIN, SERVICES_DOMAIN
from orchestrai.registry import ComponentStore
from orchestrai.registry.active_app import get_registry_for, push_active_registry_app
from orchestrai.registry.records import RegistrationRecord


class DemoPromptSection(PromptSection):
    abstract = False
    identity: ClassVar[Identity] = Identity(
        domain=PROMPT_SECTIONS_DOMAIN,
        namespace="demo",
        group="prompt",
        name="section",
    )
    instruction = "demo"


def test_get_registry_for_prompt_sections_prefers_prompt_domain():
    store = ComponentStore()
    app = type("App", (), {"component_store": store})()

    with push_active_registry_app(app):
        registry = get_registry_for(PromptSection)

    assert registry is store.registry(PROMPT_SECTIONS_DOMAIN)
    assert store.domains() == (PROMPT_SECTIONS_DOMAIN,)


def test_prompt_section_get_uses_prompt_section_registry():
    store = ComponentStore()
    store.register(RegistrationRecord(component=DemoPromptSection, identity=DemoPromptSection.identity))
    app = type("App", (), {"component_store": store})()

    with push_active_registry_app(app):
        resolved = PromptSection.get(DemoPromptSection.identity)

    assert resolved is DemoPromptSection
    assert PROMPT_SECTIONS_DOMAIN in store.domains()
    assert SERVICES_DOMAIN not in store.domains()


def test_prompt_section_identity_resolver_prefers_prompt_domain():
    store = ComponentStore()
    store.register(RegistrationRecord(component=DemoPromptSection, identity=DemoPromptSection.identity))
    app = type("App", (), {"component_store": store})()

    with push_active_registry_app(app):
        resolved = Identity.resolve.try_for_(PromptSection, DemoPromptSection.identity.as_str)

    assert resolved is DemoPromptSection
    assert store.domains() == (PROMPT_SECTIONS_DOMAIN,)
