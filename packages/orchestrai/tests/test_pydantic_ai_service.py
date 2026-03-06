"""Tests for BaseService and instruction composition."""

from pydantic import BaseModel
import pytest

from orchestrai.decorators import orca
from orchestrai.instructions import BaseInstruction, collect_instructions


class TestInstructionDecorator:
    def test_instruction_decorator_sets_order(self):
        @orca.instruction(order=25)
        class DemoInstruction(BaseInstruction):
            instruction = "demo"

        assert DemoInstruction.order == 25
        assert DemoInstruction.abstract is False

    def test_instruction_order_must_be_within_bounds(self):
        with pytest.raises(ValueError, match="between 0 and 100"):

            @orca.instruction(order=101)
            class DemoInstruction(BaseInstruction):
                instruction = "demo"

    def test_instruction_requires_base_instruction_subclass(self):
        with pytest.raises(TypeError, match="must subclass BaseInstruction"):

            @orca.instruction(order=10)
            class NotInstruction:
                pass

    def test_collect_instructions_ordering(self):
        @orca.instruction(order=90)
        class LateInstruction(BaseInstruction):
            instruction = "late"

        @orca.instruction(order=10)
        class EarlyInstruction(BaseInstruction):
            instruction = "early"

        @orca.instruction(order=10)
        class TiebreakInstruction(BaseInstruction):
            instruction = "tiebreak"

        class Service(EarlyInstruction, LateInstruction, TiebreakInstruction):
            pass

        collected = collect_instructions(Service)
        assert [cls.__name__ for cls in collected] == [
            "EarlyInstruction",
            "TiebreakInstruction",
            "LateInstruction",
        ]

    def test_collect_instructions_skips_abstract(self):
        class AbstractInstruction(BaseInstruction):
            abstract = True

        @orca.instruction(order=10)
        class ConcreteInstruction(AbstractInstruction):
            instruction = "concrete"

        class Service(ConcreteInstruction):
            pass

        collected = collect_instructions(Service)
        assert collected == [ConcreteInstruction]


class TestBaseServiceIntegration:
    def test_service_creation_with_context(self):
        from orchestrai.components.services import BaseService

        class TestSchema(BaseModel):
            message: str

        @orca.instruction(order=10)
        class TestInstruction(BaseInstruction):
            instruction = "Test instructions"

        class TestService(TestInstruction, BaseService):
            abstract = False
            response_schema = TestSchema
            model = "openai-responses:gpt-5-nano"

        service = TestService(context={"simulation_id": 123})

        assert service.context["simulation_id"] == 123
        assert service.effective_model == "openai-responses:gpt-5-nano"
        assert service._instruction_classes == [TestInstruction]

    def test_service_model_override(self):
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
