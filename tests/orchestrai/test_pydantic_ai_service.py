"""
Tests for BaseService (Pydantic AI-based service) and instruction system.

These tests verify the BaseService class, instruction decorator,
collect_instructions, and related components.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from orchestrai.instructions import BaseInstruction, collect_instructions


class TestInstructionDecorator:
    """Tests for the @instruction decorator and BaseInstruction."""

    def test_static_instruction(self):
        """Test that a static instruction class stores text."""

        class TestInstruction(BaseInstruction):
            abstract = False
            order = 50
            instruction = "Test instruction text"

        assert TestInstruction.instruction == "Test instruction text"
        assert TestInstruction.order == 50

    def test_default_order(self):
        """Test that default order is 50."""

        class TestInstruction(BaseInstruction):
            abstract = False
            instruction = "test"

        assert TestInstruction.order == 50

    def test_collect_instructions_ordering(self):
        """Test that instructions are collected in order ascending."""

        class LowPriority(BaseInstruction):
            abstract = False
            order = 90
            instruction = "low"

        class HighPriority(BaseInstruction):
            abstract = False
            order = 0
            instruction = "high"

        class MediumPriority(BaseInstruction):
            abstract = False
            order = 50
            instruction = "medium"

        class TestService(HighPriority, MediumPriority, LowPriority):
            pass

        instructions = collect_instructions(TestService)

        assert len(instructions) == 3
        assert instructions[0].order == 0
        assert instructions[0] is HighPriority
        assert instructions[1].order == 50
        assert instructions[1] is MediumPriority
        assert instructions[2].order == 90
        assert instructions[2] is LowPriority

    def test_collect_instructions_inheritance(self):
        """Test that instructions from parent classes are collected."""

        class BaseInstr(BaseInstruction):
            abstract = False
            order = 50
            instruction = "base"

        class DerivedInstr(BaseInstruction):
            abstract = False
            order = 10
            instruction = "derived"

        class DerivedService(DerivedInstr, BaseInstr):
            pass

        instructions = collect_instructions(DerivedService)

        assert len(instructions) == 2
        classes = [cls for cls in instructions]
        assert DerivedInstr in classes
        assert BaseInstr in classes

    def test_collect_instructions_skips_abstract(self):
        """Test that abstract instruction classes are skipped."""

        class AbstractInstr(BaseInstruction):
            abstract = True
            instruction = "abstract"

        class ConcreteInstr(BaseInstruction):
            abstract = False
            order = 10
            instruction = "concrete"

        class TestService(AbstractInstr, ConcreteInstr):
            pass

        instructions = collect_instructions(TestService)

        assert len(instructions) == 1
        assert instructions[0] is ConcreteInstr

    def test_collect_instructions_tiebreak_by_name(self):
        """Test that instructions with same order are sorted by class name."""

        class BInstruction(BaseInstruction):
            abstract = False
            order = 50
            instruction = "b"

        class AInstruction(BaseInstruction):
            abstract = False
            order = 50
            instruction = "a"

        class TestService(BInstruction, AInstruction):
            pass

        instructions = collect_instructions(TestService)

        assert len(instructions) == 2
        assert instructions[0] is AInstruction
        assert instructions[1] is BInstruction


class TestInstructionRendering:
    """Tests for rendering instruction content."""

    @pytest.mark.asyncio
    async def test_render_static_instruction(self):
        """Test rendering a static instruction."""

        class StaticInstr(BaseInstruction):
            abstract = False
            instruction = "Static instruction text"

        result = await StaticInstr.render_instruction(StaticInstr)
        assert result == "Static instruction text"

    @pytest.mark.asyncio
    async def test_render_dynamic_instruction(self):
        """Test rendering a dynamic instruction with custom render_instruction."""

        class DynamicInstr(BaseInstruction):
            abstract = False

            async def render_instruction(self) -> str:
                return f"Dynamic: {self.context.get('name', 'unknown')}"

        # Simulate calling with a service instance that has context
        mock_service = MagicMock()
        mock_service.context = {"name": "TestPatient"}

        result = await DynamicInstr.render_instruction(mock_service)
        assert result == "Dynamic: TestPatient"

    @pytest.mark.asyncio
    async def test_render_none_instruction(self):
        """Test that None instruction returns None."""

        class EmptyInstr(BaseInstruction):
            abstract = False
            instruction = None

        result = await EmptyInstr.render_instruction(EmptyInstr)
        assert result is None


class TestBaseServiceIntegration:
    """Integration tests for BaseService (Pydantic AI-based)."""

    def test_service_creation_with_context(self):
        """Test that service can be created with context."""
        from orchestrai.components.services import BaseService

        class TestSchema(BaseModel):
            message: str

        class TestInstr(BaseInstruction):
            abstract = False
            order = 50
            instruction = "Test instructions"

        class TestService(TestInstr, BaseService):
            abstract = False
            response_schema = TestSchema
            model = "openai-responses:gpt-5-nano"

        service = TestService(context={"simulation_id": 123})

        assert service.context["simulation_id"] == 123
        assert service.effective_model == "openai-responses:gpt-5-nano"
        assert len(service._instruction_classes) == 1

    def test_service_model_override(self):
        """Test that model can be overridden at instance level."""
        from orchestrai.components.services import BaseService

        class TestSchema(BaseModel):
            message: str

        class TestService(BaseService):
            abstract = False
            response_schema = TestSchema
            model = "openai-responses:gpt-5-nano"

        service = TestService(model="anthropic:claude-3-5-sonnet")

        assert service.effective_model == "anthropic:claude-3-5-sonnet"

    def test_required_context_validation(self):
        """Test that missing required context keys raise error."""
        from orchestrai.components.services import BaseService

        class TestSchema(BaseModel):
            message: str

        class TestService(BaseService):
            abstract = False
            response_schema = TestSchema
            required_context_keys = ("simulation_id", "user_id")

        service = TestService(context={"simulation_id": 123})

        with pytest.raises(ValueError, match="Missing required context keys"):
            service.check_required_context()

    def test_setup_merges_context(self):
        """Test that setup merges incoming context."""
        from orchestrai.components.services import BaseService

        class TestSchema(BaseModel):
            message: str

        class TestService(BaseService):
            abstract = False
            response_schema = TestSchema

        service = TestService(context={"initial": "value"})
        service.setup(context={"added": "context"})

        assert service.context["initial"] == "value"
        assert service.context["added"] == "context"

    def test_pydantic_ai_service_alias(self):
        """Test that PydanticAIService is an alias for BaseService."""
        from orchestrai.components.services import BaseService, PydanticAIService

        assert PydanticAIService is BaseService
