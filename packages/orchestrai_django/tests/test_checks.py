from __future__ import annotations

import types

from orchestrai.identity import Identity
from orchestrai_django import checks as orchestrai_checks


def test_check_orchestrai_settings_reports_missing_configuration(settings):
    settings.orchestrai = {
        "PROVIDERS": {"openai": {"backend": "openai", "api_key_env": "OPENAI_API_KEY"}},
        "CLIENTS": {"chat-default": {"backend": "missing-backend", "default": True}},
    }

    messages = orchestrai_checks.check_orchestrai_settings()
    ids = {message.id for message in messages}

    assert "orchestrai.E008" in ids


def test_check_orchestrai_registries_reports_collisions_and_invalid_identity(settings, monkeypatch):
    settings.SIMCORE_COLLISIONS_STRICT = True

    class FakeRegistry:
        def __init__(self, collisions=None, identities=None):
            self._collisions = collisions or []
            self._identities = identities or []

        def collisions(self):
            return self._collisions

        def list(self):
            return [types.SimpleNamespace(identity=ident) for ident in self._identities]

    fake_with_collision = FakeRegistry(
        collisions=[("services", "demo", "group", "duplicate")],
        identities=[
            ("services", "demo", "group", "ok"),
            ("services", "demo", "group", "bad name!"),
        ],
    )
    fake_ok = FakeRegistry()

    monkeypatch.setattr(orchestrai_checks, "service_registry", fake_with_collision)
    monkeypatch.setattr(orchestrai_checks, "instruction_registry", fake_ok)
    monkeypatch.setattr(orchestrai_checks, "schema_registry", fake_ok)

    messages = orchestrai_checks.check_orchestrai_registries()
    ids = {message.id for message in messages}

    assert "SIMCORE-ID-001" in ids
    assert "SIMCORE-ID-002" in ids


def test_check_orchestrai_service_pairings_reports_missing_schema(monkeypatch):
    class DemoService:
        identity = Identity("services", "demo", "group", "missing_schema")

    fake_service_registry = types.SimpleNamespace(all=lambda: [DemoService])
    fake_empty_lookup = types.SimpleNamespace(get=lambda ident: None)

    monkeypatch.setattr(orchestrai_checks, "service_registry", fake_service_registry)
    monkeypatch.setattr(orchestrai_checks, "schema_registry", fake_empty_lookup)
    monkeypatch.setattr(orchestrai_checks, "instruction_registry", fake_empty_lookup)

    messages = orchestrai_checks.check_orchestrai_service_pairings()
    ids = {message.id for message in messages}

    assert "SIMCORE-ID-012A" in ids
