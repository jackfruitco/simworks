"""Integration tests for chatlab Stitch services."""

from asgiref.sync import sync_to_async
import pytest

from apps.chatlab.orca.instructions import (
    StitchConversationContextInstruction,
    StitchPersonaInstruction,
    StitchReplyDetailInstruction,
    StitchRoleInstruction,
    StitchScenarioGroundTruthInstruction,
    StitchSchemaContractInstruction,
    StitchToneInstruction,
)
from apps.chatlab.orca.schemas import StitchReplyOutputSchema
from apps.chatlab.orca.services.stitch import GenerateStitchReply


class TestGenerateStitchReplyService:
    def test_service_has_response_schema(self):
        assert hasattr(GenerateStitchReply, "response_schema")
        assert GenerateStitchReply.response_schema == StitchReplyOutputSchema

    def test_service_required_context_keys(self):
        assert hasattr(GenerateStitchReply, "required_context_keys")
        assert "simulation_id" in GenerateStitchReply.required_context_keys
        assert "conversation_id" in GenerateStitchReply.required_context_keys

    def test_service_collects_instruction_classes(self):
        service = GenerateStitchReply(context={"simulation_id": 1, "conversation_id": 2})
        assert StitchPersonaInstruction in service._instruction_classes
        assert StitchRoleInstruction in service._instruction_classes
        assert StitchScenarioGroundTruthInstruction in service._instruction_classes
        assert StitchConversationContextInstruction in service._instruction_classes
        assert StitchReplyDetailInstruction in service._instruction_classes
        assert StitchSchemaContractInstruction in service._instruction_classes
        assert StitchToneInstruction in service._instruction_classes

    def test_instruction_ordering_layers(self):
        service = GenerateStitchReply(context={"simulation_id": 1, "conversation_id": 2})
        names = [cls.__name__ for cls in service._instruction_classes]

        assert names.index("StitchPersonaInstruction") < names.index("StitchRoleInstruction")
        assert names.index("StitchRoleInstruction") < names.index(
            "StitchScenarioGroundTruthInstruction"
        )
        assert names.index("StitchScenarioGroundTruthInstruction") < names.index(
            "StitchConversationContextInstruction"
        )
        assert names.index("StitchRoleInstruction") < names.index(
            "StitchConversationContextInstruction"
        )
        assert names.index("StitchConversationContextInstruction") < names.index(
            "StitchDebriefInstruction"
        )
        assert names.index("StitchDebriefInstruction") < names.index(
            "StitchSchemaContractInstruction"
        )

    @pytest.mark.asyncio
    async def test_cross_service_previous_response_fallback(self, monkeypatch):
        class DummyCall:
            provider_response_id = "resp_prev_123"

        class DummyQuerySet:
            def exclude(self, **_kwargs):
                return self

            def order_by(self, *_args):
                return self

            async def afirst(self):
                return DummyCall()

        class DummyManager:
            def filter(self, **_kwargs):
                return DummyQuerySet()

        class DummyServiceCall:
            objects = DummyManager()

        from orchestrai_django import models as od_models

        monkeypatch.setattr(od_models, "ServiceCall", DummyServiceCall)

        service = GenerateStitchReply(context={"simulation_id": 1, "conversation_id": 2})
        await service._aset_previous_response_fallback()

        assert service.context["previous_response_id"] == "resp_prev_123"
        assert service.context["previous_provider_response_id"] == "resp_prev_123"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestStitchScenarioGroundTruthInstruction:
    async def test_renders_persisted_ground_truth(self, django_user_model):
        from apps.accounts.models import UserRole
        from apps.simcore.models import Simulation

        role = await UserRole.objects.acreate(title="Stitch Ground Truth")
        user = await sync_to_async(django_user_model.objects.create_user)(
            email="stitch-ground-truth@example.com",
            password="testpass123",
            role=role,
        )
        sim = await Simulation.objects.acreate(
            user=user,
            diagnosis="Acute appendicitis",
            chief_complaint="Right lower quadrant abdominal pain",
        )

        instruction = StitchScenarioGroundTruthInstruction()
        instruction.context = {"simulation_id": sim.id}
        rendered = await instruction.render_instruction()

        assert "### Scenario Ground Truth" in rendered
        assert "- Chief complaint: Right lower quadrant abdominal pain" in rendered
        assert "- Correct diagnosis: Acute appendicitis" in rendered
        assert "authoritative case answer" in rendered
        assert "Use conversation history only" in rendered

    async def test_renders_limitation_when_ground_truth_missing(self, django_user_model):
        from apps.accounts.models import UserRole
        from apps.simcore.models import Simulation

        role = await UserRole.objects.acreate(title="Stitch Missing Ground Truth")
        user = await sync_to_async(django_user_model.objects.create_user)(
            email="stitch-missing-ground-truth@example.com",
            password="testpass123",
            role=role,
        )
        sim = await Simulation.objects.acreate(user=user)

        instruction = StitchScenarioGroundTruthInstruction()
        instruction.context = {"simulation_id": sim.id}
        rendered = await instruction.render_instruction()

        assert "### Scenario Ground Truth" in rendered
        assert "Persisted scenario ground truth is unavailable" in rendered
        assert "Do not present an inferred diagnosis as certain" in rendered
