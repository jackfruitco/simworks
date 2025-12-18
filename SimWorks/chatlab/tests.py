import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrai.components.services.exceptions import ServiceError


@pytest.fixture()
def chatlab_modules(monkeypatch):
    base_path = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(base_path))

    for name in (
        "chatlab.utils",
        "chatlab.consumers",
        "chatlab.models",
        "chatlab.apps",
        "simulation.models",
        "simulation.utils",
        "core.utils",
    ):
        import sys

        sys.modules.pop(name, None)

    import sys
    import types

    core_utils = types.ModuleType("core.utils")
    core_utils.remove_null_keys = lambda data: {k: v for k, v in data.items() if v is not None}
    monkeypatch.setitem(sys.modules, "core.utils", core_utils)

    chatlab_apps = types.ModuleType("chatlab.apps")

    class ChatLabConfig:
        name = "chatlab"
        label = "chatlab"

    chatlab_apps.ChatLabConfig = ChatLabConfig
    monkeypatch.setitem(sys.modules, "chatlab.apps", chatlab_apps)

    simulation_models = types.ModuleType("simulation.models")

    class Simulation:
        abuild = AsyncMock()

    class LabResult:
        pass

    class RadResult:
        pass

    class SimulationMetadata:
        pass

    simulation_models.Simulation = Simulation
    simulation_models.LabResult = LabResult
    simulation_models.RadResult = RadResult
    simulation_models.SimulationMetadata = SimulationMetadata
    monkeypatch.setitem(sys.modules, "simulation.models", simulation_models)

    simulation_utils = types.ModuleType("simulation.utils")
    simulation_utils.get_user_initials = lambda username: username[:2]
    simulation_utils.generate_fake_name = AsyncMock(return_value="Test User")
    monkeypatch.setitem(sys.modules, "simulation.utils", simulation_utils)

    chatlab_orca = types.ModuleType("chatlab.orca")
    services_mod = types.ModuleType("chatlab.orca.services")

    class GenerateInitialResponse:
        @classmethod
        def using(cls, **kwargs):  # pragma: no cover - patched in tests
            return SimpleNamespace(enqueue=MagicMock())

    class GenerateReplyResponse:
        @classmethod
        def using(cls, **kwargs):  # pragma: no cover - patched in tests
            return SimpleNamespace(enqueue=MagicMock())

    services_mod.GenerateInitialResponse = GenerateInitialResponse
    services_mod.GenerateReplyResponse = GenerateReplyResponse
    chatlab_orca.services = services_mod

    monkeypatch.setitem(sys.modules, "chatlab.orca", chatlab_orca)
    monkeypatch.setitem(sys.modules, "chatlab.orca.services", services_mod)

    chatlab_models = types.ModuleType("chatlab.models")

    class ChatSession:
        objects = SimpleNamespace(acreate=AsyncMock())

    class Message:
        objects = SimpleNamespace()

    class MessageMediaLink:
        pass

    class RoleChoices:
        USER = "USER"

    chatlab_models.ChatSession = ChatSession
    chatlab_models.Message = Message
    chatlab_models.MessageMediaLink = MessageMediaLink
    chatlab_models.RoleChoices = RoleChoices
    monkeypatch.setitem(sys.modules, "chatlab.models", chatlab_models)

    utils = importlib.import_module("chatlab.utils")
    consumers = importlib.import_module("chatlab.consumers")

    return SimpleNamespace(utils=utils, consumers=consumers, models=chatlab_models, simulation_models=simulation_models)


@pytest.mark.asyncio
async def test_create_new_simulation_uses_service_call(chatlab_modules, monkeypatch):
    utils = chatlab_modules.utils

    user = SimpleNamespace(id=7, username="demo")
    simulation = SimpleNamespace(id=11, adelete=AsyncMock())
    session = SimpleNamespace(id=3)

    monkeypatch.setattr(utils, "generate_fake_name", AsyncMock(return_value="Test User"))
    monkeypatch.setattr(chatlab_modules.simulation_models.Simulation, "abuild", AsyncMock(return_value=simulation))
    monkeypatch.setattr(utils.ChatSession, "objects", SimpleNamespace(acreate=AsyncMock(return_value=session)))

    calls: dict = {}

    class DummyCall:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.enqueue = MagicMock(return_value="queued")

    def fake_using(**kwargs):
        calls["kwargs"] = kwargs
        calls["call"] = DummyCall(**kwargs)
        return calls["call"]

    import chatlab.orca.services as services

    monkeypatch.setattr(services.GenerateInitialResponse, "using", staticmethod(fake_using))

    result = await utils.create_new_simulation(user=user, modifiers=["fast"], force=False)

    assert result is simulation
    assert calls["kwargs"] == {"simulation_id": simulation.id, "user_id": user.id}
    calls["call"].enqueue.assert_called_once_with()


@pytest.mark.asyncio
async def test_create_new_simulation_cleans_up_on_failure(chatlab_modules, monkeypatch):
    utils = chatlab_modules.utils

    user = SimpleNamespace(id=8, username="failer")
    simulation = SimpleNamespace(id=13, adelete=AsyncMock())
    session = SimpleNamespace(id=4)

    monkeypatch.setattr(utils, "generate_fake_name", AsyncMock(return_value="Test User"))
    monkeypatch.setattr(chatlab_modules.simulation_models.Simulation, "abuild", AsyncMock(return_value=simulation))
    monkeypatch.setattr(utils.ChatSession, "objects", SimpleNamespace(acreate=AsyncMock(return_value=session)))

    class FailingCall:
        def __init__(self, **_kwargs):
            self.enqueue = MagicMock(side_effect=ServiceError("boom"))

    import chatlab.orca.services as services

    monkeypatch.setattr(services.GenerateInitialResponse, "using", staticmethod(lambda **_kwargs: FailingCall()))

    with pytest.raises(utils.SimulationSchedulingError):
        await utils.create_new_simulation(user=user)

    simulation.adelete.assert_awaited_once()


@pytest.mark.asyncio
async def test_consumer_generates_patient_response_via_service_call(chatlab_modules, monkeypatch):
    consumers = chatlab_modules.consumers

    consumer = SimpleNamespace(simulation=SimpleNamespace(pk=21))
    user_msg = SimpleNamespace(pk=99)

    calls: dict = {}

    class DummyCall:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.enqueue = MagicMock(return_value=None)

    def fake_using(**kwargs):
        calls["kwargs"] = kwargs
        calls["call"] = DummyCall(**kwargs)
        return calls["call"]

    import chatlab.orca.services as services

    monkeypatch.setattr(services.GenerateReplyResponse, "using", staticmethod(fake_using))

    await consumers.ChatConsumer._generate_patient_response(consumer, user_msg)

    assert calls["kwargs"] == {"simulation_id": 21, "user_msg_id": 99}
    calls["call"].enqueue.assert_called_once_with()
