import importlib
from types import SimpleNamespace

import pytest

from orchestrai.components.services.discovery import discover_services
from orchestrai.components.services.exceptions import ServiceDiscoveryError
from orchestrai.components.services.registry import ServiceRegistry, ensure_service_registry
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.registry.active_app import push_active_registry_app
from orchestrai.registry.base import ComponentRegistry
from orchestrai.registry.component_store import ComponentStore


class EchoService(BaseService):
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="tests", group="echo", name="svc")


def test_ensure_service_registry_upgrades_plain_registry():
    store = ComponentStore()
    store._registries[SERVICES_DOMAIN] = ComponentRegistry()
    store._registries[SERVICES_DOMAIN].register(EchoService)
    app = SimpleNamespace(component_store=store)

    with push_active_registry_app(app):
        registry = ensure_service_registry()

    assert isinstance(registry, ServiceRegistry)
    assert registry.get(EchoService) is EchoService


def test_ensure_service_registry_without_store_raises(monkeypatch):
    registry_module = importlib.import_module("orchestrai.registry.services")

    monkeypatch.setattr(registry_module, "get_component_store", lambda app=None: None)
    with pytest.raises(LookupError):
        registry_module.ensure_service_registry()


def test_discover_services_happy_path_and_missing_module():
    assert discover_services(["math"]) == ["math"]

    with pytest.raises(ServiceDiscoveryError):
        discover_services(["nonexistent.discovery.module"])
