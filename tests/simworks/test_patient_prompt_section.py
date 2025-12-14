import importlib
import sys
import types

import pytest
from django.core.exceptions import ObjectDoesNotExist


class DummyManager:
    def __init__(self, simulation):
        self.simulation = simulation

    async def aget(self, pk):
        if pk == self.simulation.pk:
            return self.simulation
        raise ObjectDoesNotExist


class DummySimulation:
    def __init__(self, pk: int, full_name: str):
        self.pk = pk
        self.sim_patient_full_name = full_name


@pytest.fixture()
def patient_module(monkeypatch):
    simulation = DummySimulation(pk=101, full_name="Jamie Patient")
    DummySimulation.objects = DummyManager(simulation)

    dummy_models = types.SimpleNamespace(Simulation=DummySimulation)
    monkeypatch.setitem(sys.modules, "simulation.models", dummy_models)
    sys.modules.pop("simulation.orca.prompts.sections.patient", None)

    module = importlib.import_module("simulation.orca.prompts.sections.patient")
    return module, simulation


@pytest.mark.asyncio
async def test_patient_section_requires_context(patient_module):
    module, _ = patient_module
    section = module.PatientNameSection()

    with pytest.raises(ValueError) as exc_info:
        await section.render_instruction()

    assert "Missing required context variable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_patient_section_renders_from_simulation_object(patient_module):
    module, simulation = patient_module
    section = module.PatientNameSection()

    rendered = await section.render_instruction(simulation=simulation)

    assert simulation.sim_patient_full_name in rendered


@pytest.mark.asyncio
async def test_patient_section_resolves_simulation_id(patient_module):
    module, simulation = patient_module
    section = module.PatientNameSection()

    rendered = await section.render_instruction(simulation_id=simulation.pk)

    assert simulation.sim_patient_full_name in rendered
