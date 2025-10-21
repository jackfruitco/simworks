from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Optional, Tuple

import pytest

# ---------------------------------------------------------------------------
# Import helpers: ensure the workspace packages are importable when the
# tests run in isolation (without editable installs).
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = ROOT / "packages"
for rel in ("simcore_ai/src", "simcore_ai_django/src"):
    pkg_path = PKG_ROOT / rel
    if str(pkg_path) not in sys.path:
        sys.path.insert(0, str(pkg_path))

from simcore_ai.providers.base import BaseProvider
from simcore_ai_django import health


class StubProvider(BaseProvider):
    """Test helper implementing the abstract provider contract."""

    def __init__(self, name: str = "stub", *, fail_with: Exception | None = None) -> None:
        super().__init__(name=name)
        self.fail_with = fail_with
        self.observed_timeout: Optional[float] = None

    async def call(self, req, timeout: float | None = None):  # pragma: no cover - not used
        raise NotImplementedError

    async def stream(self, req):  # pragma: no cover - not used
        if False:  # pragma: no cover - appease linters
            yield req

    async def healthcheck(self, *, timeout: Optional[float] = None) -> Tuple[bool, str]:
        self.observed_timeout = timeout
        if self.fail_with:
            raise self.fail_with
        return True, f"{self.name} healthy"


@pytest.fixture
def stub_client() -> SimpleNamespace:
    return SimpleNamespace(provider=StubProvider())


def test_healthcheck_client_runs_provider_healthcheck(stub_client):
    ok, message = health.healthcheck_client(stub_client, timeout_s=3.2)
    assert ok is True
    assert "healthy" in message
    assert stub_client.provider.observed_timeout == 3.2


def test_healthcheck_client_uses_existing_loop_when_asyncio_run_fails(monkeypatch, stub_client):
    loop = asyncio.new_event_loop()
    def fake_run(coro):
        coro.close()
        raise RuntimeError("running")

    monkeypatch.setattr(health.asyncio, "run", fake_run)
    monkeypatch.setattr(health.asyncio, "get_event_loop", lambda: loop)
    try:
        ok, _ = health.healthcheck_client(stub_client, timeout_s=1.0)
        assert ok is True
    finally:
        loop.close()


def test_healthcheck_client_reports_provider_errors():
    failing_provider = StubProvider(fail_with=RuntimeError("boom"))
    client = SimpleNamespace(provider=failing_provider)
    ok, message = health.healthcheck_client(client)
    assert ok is False
    assert "boom" in message


def test_healthcheck_client_static_checks_missing_api_key():
    provider = SimpleNamespace(name="StaticProvider", api_key=None)
    client = SimpleNamespace(provider=provider)
    ok, message = health.healthcheck_client(client)
    assert ok is False
    assert "missing api_key" in message


def test_healthcheck_client_static_checks_pass_when_api_key_present():
    provider = SimpleNamespace(name="StaticProvider", api_key="abc123")
    client = SimpleNamespace(provider=provider)
    ok, message = health.healthcheck_client(client)
    assert ok is True
    assert "static check passed" in message


def test_healthcheck_all_registered_aggregates_and_logs(monkeypatch, caplog):
    healthy = StubProvider(name="healthy")
    no_key_provider = SimpleNamespace(name="Broken", api_key=None)
    clients = {
        "healthy": SimpleNamespace(provider=healthy),
        "broken": SimpleNamespace(provider=no_key_provider),
    }
    monkeypatch.setattr(health, "list_clients", lambda: clients)

    caplog.set_level("INFO")
    results = health.healthcheck_all_registered(timeout_s=2.5)

    assert results["healthy"][0] is True
    assert results["broken"][0] is False
    assert healthy.observed_timeout == 2.5

    messages = [record.message for record in caplog.records]
    assert any("AI healthcheck OK" in msg for msg in messages)
    assert any("AI healthcheck FAIL" in msg for msg in messages)

