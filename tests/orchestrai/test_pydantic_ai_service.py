"""
Tests for BaseService (Pydantic AI-based service).

These tests verify the BaseService class and related components.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from orchestrai.prompts import system_prompt
from orchestrai.prompts.decorators import (
    collect_prompts,
    is_system_prompt,
    get_prompt_weight,
    render_prompt_methods,
)


class TestSystemPromptDecorator:
    """Tests for the @system_prompt decorator."""

    def test_decorator_marks_method(self):
        """Test that decorator marks methods correctly."""

        class TestClass:
            @system_prompt
            def my_prompt(self) -> str:
                return "test"

        assert is_system_prompt(TestClass.my_prompt)
        assert get_prompt_weight(TestClass.my_prompt) == 100  # Default

    def test_decorator_with_weight(self):
        """Test that weight parameter is stored."""

        class TestClass:
            @system_prompt(weight=50)
            def my_prompt(self) -> str:
                return "test"

        assert is_system_prompt(TestClass.my_prompt)
        assert get_prompt_weight(TestClass.my_prompt) == 50

    def test_collect_prompts_ordering(self):
        """Test that prompts are collected in weight order (descending)."""

        class TestClass:
            @system_prompt(weight=10)
            def low_priority(self) -> str:
                return "low"

            @system_prompt(weight=100)
            def high_priority(self) -> str:
                return "high"

            @system_prompt(weight=50)
            def medium_priority(self) -> str:
                return "medium"

        prompts = collect_prompts(TestClass)

        assert len(prompts) == 3
        assert prompts[0].weight == 100
        assert prompts[0].name == "high_priority"
        assert prompts[1].weight == 50
        assert prompts[1].name == "medium_priority"
        assert prompts[2].weight == 10
        assert prompts[2].name == "low_priority"

    def test_collect_prompts_inheritance(self):
        """Test that prompts from parent classes are collected."""

        class BaseClass:
            @system_prompt(weight=100)
            def base_prompt(self) -> str:
                return "base"

        class DerivedClass(BaseClass):
            @system_prompt(weight=50)
            def derived_prompt(self) -> str:
                return "derived"

        prompts = collect_prompts(DerivedClass)

        assert len(prompts) == 2
        names = [p.name for p in prompts]
        assert "base_prompt" in names
        assert "derived_prompt" in names


class TestRenderPromptMethods:
    """Tests for rendering prompt methods."""

    @pytest.mark.asyncio
    async def test_render_sync_methods(self):
        """Test rendering synchronous prompt methods."""

        class TestClass:
            @system_prompt(weight=100)
            def first(self) -> str:
                return "First prompt"

            @system_prompt(weight=50)
            def second(self) -> str:
                return "Second prompt"

        instance = TestClass()
        prompts = collect_prompts(TestClass)
        result = await render_prompt_methods(instance, prompts)

        assert "First prompt" in result
        assert "Second prompt" in result
        # First should come before second due to weight
        assert result.index("First prompt") < result.index("Second prompt")

    @pytest.mark.asyncio
    async def test_render_async_methods(self):
        """Test rendering asynchronous prompt methods."""

        class TestClass:
            @system_prompt(weight=100)
            async def async_prompt(self) -> str:
                return "Async result"

        instance = TestClass()
        prompts = collect_prompts(TestClass)
        result = await render_prompt_methods(instance, prompts)

        assert "Async result" in result

    @pytest.mark.asyncio
    async def test_render_with_none_result(self):
        """Test that None results are skipped."""

        class TestClass:
            @system_prompt(weight=100)
            def returns_none(self) -> str | None:
                return None

            @system_prompt(weight=50)
            def returns_value(self) -> str:
                return "Has value"

        instance = TestClass()
        prompts = collect_prompts(TestClass)
        result = await render_prompt_methods(instance, prompts)

        assert "Has value" in result
        assert result.strip() == "Has value"


class TestBaseServiceIntegration:
    """Integration tests for BaseService (Pydantic AI-based)."""

    def test_service_creation_with_context(self):
        """Test that service can be created with context."""
        from orchestrai.components.services import BaseService

        class TestSchema(BaseModel):
            message: str

        class TestService(BaseService):
            abstract = False
            response_schema = TestSchema
            model = "openai-responses:gpt-5-nano"

            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "Test instructions"

        service = TestService(context={"simulation_id": 123})

        assert service.context["simulation_id"] == 123
        assert service.effective_model == "openai-responses:gpt-5-nano"
        assert len(service._prompt_methods) == 1

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
