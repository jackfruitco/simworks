"""Integration tests for chatlab Stitch services."""

import pytest

from apps.chatlab.orca.instructions import (
    StitchConversationContextInstruction,
    StitchPersonaInstruction,
    StitchReplyDetailInstruction,
    StitchRoleInstruction,
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
        assert StitchConversationContextInstruction in service._instruction_classes
        assert StitchReplyDetailInstruction in service._instruction_classes
        assert StitchSchemaContractInstruction in service._instruction_classes
        assert StitchToneInstruction in service._instruction_classes

    def test_instruction_ordering_layers(self):
        service = GenerateStitchReply(context={"simulation_id": 1, "conversation_id": 2})
        names = [cls.__name__ for cls in service._instruction_classes]

        assert names.index("StitchPersonaInstruction") < names.index("StitchRoleInstruction")
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
