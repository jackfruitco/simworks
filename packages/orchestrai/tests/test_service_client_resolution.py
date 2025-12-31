import pytest

from orchestrai._state import push_current_app
from orchestrai.app import OrchestrAI
from orchestrai.components.services.service import BaseService
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN


class DummyClient:
    def __init__(self, label: str):
        self.label = label
        self.requests: list[dict] = []

    async def send_request(self, request):
        self.requests.append(request)
        return {"client": self.label, "request": request}


class EchoClientService(BaseService):
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="tests", group="svc", name="echo")
    provider_name = None

    async def arun(self, *, call, **ctx):
        payload = {"value": ctx.get("value")}
        call.request = payload
        return await call.client.send_request(payload)


class PreferredClientService(EchoClientService):
    provider_name = "preferred"


def _make_app(mode: str = "pod") -> OrchestrAI:
    app = OrchestrAI("svc-client-test")
    app.conf["MODE"] = mode
    return app


def test_override_client_wins_when_not_single():
    app = _make_app("pod")
    default_client = DummyClient("default")
    override_client = DummyClient("override")
    app.set_client("default", default_client)
    app.set_default_client("default")

    with push_current_app(app):
        call = EchoClientService.task.using(client=override_client).run(value=1)

    assert call.client is override_client
    assert override_client.requests == [{"value": 1}]
    assert default_client.requests == []


def test_service_default_client_used_when_no_override():
    app = _make_app("pod")
    preferred_client = DummyClient("preferred")
    fallback_client = DummyClient("fallback")
    app.set_client("preferred", preferred_client)
    app.set_client("default", fallback_client)
    app.set_default_client("default")

    with push_current_app(app):
        call = PreferredClientService.task.run(value=2)

    assert call.client is preferred_client
    assert preferred_client.requests == [{"value": 2}]
    assert fallback_client.requests == []


def test_app_default_client_used_when_no_hints():
    app = _make_app("pod")
    default_client = DummyClient("default")
    app.set_client("default", default_client)
    app.set_default_client("default")

    with push_current_app(app):
        call = EchoClientService.task.run(value=3)

    assert call.client is default_client
    assert default_client.requests == [{"value": 3}]


def test_single_mode_overrides_everything():
    app = _make_app("single")
    single_client = DummyClient("single")
    override_client = DummyClient("override")
    app.set_client("solo", single_client)
    app.set_default_client("solo")

    with push_current_app(app):
        call = PreferredClientService.task.using(client=override_client).run(value=4)

    assert call.client is single_client
    assert single_client.requests == [{"value": 4}]
    assert override_client.requests == []


def test_call_captures_request_payload():
    app = _make_app("pod")
    client = DummyClient("recording")
    app.set_client("default", client)
    app.set_default_client("default")

    with push_current_app(app):
        call = EchoClientService.task.run(value="payload")

    assert call.request == {"value": "payload"}
    assert client.requests == [{"value": "payload"}]
