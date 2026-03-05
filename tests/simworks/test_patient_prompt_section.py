import pytest


class DummySimulation:
    def __init__(self, pk: int, full_name: str):
        self.pk = pk
        self.sim_patient_full_name = full_name


class DummyManager:
    def __init__(self, simulation: DummySimulation):
        self.simulation = simulation

    async def aget(self, pk):
        if pk == self.simulation.pk:
            return self.simulation
        raise ValueError("not found")


@pytest.mark.asyncio
async def test_patient_name_instructions_defaults_when_no_context():
    from apps.chatlab.orca.services.patient import GenerateInitialResponse

    service = GenerateInitialResponse(context={})

    rendered = await service.patient_name_instructions()
    assert rendered == "You are a standardized patient."


@pytest.mark.asyncio
async def test_patient_name_instructions_uses_simulation_from_context():
    from apps.chatlab.orca.services.patient import GenerateInitialResponse

    simulation = DummySimulation(pk=101, full_name="Jamie Patient")
    service = GenerateInitialResponse(context={"simulation": simulation})

    rendered = await service.patient_name_instructions()
    assert "Jamie Patient" in rendered


@pytest.mark.asyncio
async def test_patient_name_instructions_resolves_simulation_id(monkeypatch):
    from apps.chatlab.orca.services.patient import GenerateInitialResponse
    from apps.simcore.models import Simulation

    simulation = DummySimulation(pk=101, full_name="Jamie Patient")
    monkeypatch.setattr(Simulation, "objects", DummyManager(simulation))

    service = GenerateInitialResponse(context={"simulation_id": 101})
    rendered = await service.patient_name_instructions()

    assert "Jamie Patient" in rendered
