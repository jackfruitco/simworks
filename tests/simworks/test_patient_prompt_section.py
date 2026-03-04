"""Tests for patient instruction classes."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.chatlab.orca.instructions.patient_name import PatientNameInstruction


class DummySimulation:
    def __init__(self, pk: int, full_name: str):
        self.pk = pk
        self.sim_patient_full_name = full_name


@pytest.mark.asyncio
async def test_patient_name_instruction_with_simulation_object():
    """Test rendering when simulation object is already in context."""
    sim = DummySimulation(pk=101, full_name="Jamie Patient")

    # Create a mock service instance with context
    mock_service = MagicMock()
    mock_service.context = {"simulation_id": 101, "simulation": sim}

    result = await PatientNameInstruction.render_instruction(mock_service)

    assert "Jamie Patient" in result


@pytest.mark.asyncio
async def test_patient_name_instruction_fallback_no_context():
    """Test rendering when no simulation context is available."""
    mock_service = MagicMock()
    mock_service.context = {}

    result = await PatientNameInstruction.render_instruction(mock_service)

    assert result == "You are a standardized patient."


@pytest.mark.asyncio
async def test_patient_name_instruction_with_simulation_id():
    """Test rendering when only simulation_id is in context."""
    sim = DummySimulation(pk=101, full_name="Jamie Patient")

    mock_manager = AsyncMock()
    mock_manager.aget = AsyncMock(return_value=sim)

    mock_service = MagicMock()
    mock_service.context = {"simulation_id": 101}

    with patch("apps.simcore.models.Simulation.objects", mock_manager):
        result = await PatientNameInstruction.render_instruction(mock_service)

    assert "Jamie Patient" in result


def test_patient_name_instruction_required_context_keys():
    """Test that simulation_id is listed as required."""
    assert "simulation_id" in PatientNameInstruction.required_context_keys


def test_patient_name_instruction_order():
    """Test that order is 0 (highest priority)."""
    assert PatientNameInstruction.order == 0
