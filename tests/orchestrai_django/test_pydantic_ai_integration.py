"""
Tests for Django Pydantic AI integration.

These tests verify the DjangoPydanticAIService and related Django components.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel


class TestServiceCallModel:
    """Tests for the new ServiceCall model."""

    @pytest.mark.django_db
    def test_service_call_creation(self):
        """Test creating a ServiceCall record."""
        from orchestrai_django.models import ServiceCall, CallStatus
        import uuid

        call = ServiceCall.objects.create(
            id=str(uuid.uuid4()),
            service_identity="services.test.example.TestService",
            status=CallStatus.PENDING,
            input={"param": "value"},
            context={"simulation_id": 123},
        )

        assert call.pk is not None
        assert call.status == CallStatus.PENDING
        assert call.input == {"param": "value"}
        assert call.context["simulation_id"] == 123

    @pytest.mark.django_db
    def test_mark_running(self):
        """Test marking a call as running."""
        from orchestrai_django.models import ServiceCall, CallStatus
        import uuid

        call = ServiceCall.objects.create(
            id=str(uuid.uuid4()),
            service_identity="services.test.example.TestService",
            status=CallStatus.PENDING,
        )

        call.mark_running()

        assert call.status == CallStatus.IN_PROGRESS
        assert call.started_at is not None

    @pytest.mark.django_db
    def test_mark_completed(self):
        """Test marking a call as completed with result data."""
        from orchestrai_django.models import ServiceCall, CallStatus
        import uuid

        call = ServiceCall.objects.create(
            id=str(uuid.uuid4()),
            service_identity="services.test.example.TestService",
            status=CallStatus.IN_PROGRESS,
        )

        call.mark_completed(
            output_data={"message": "Hello"},
            usage_json={
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            },
            model_name="gpt-4o",
        )

        assert call.status == CallStatus.COMPLETED
        assert call.finished_at is not None
        assert call.output_data == {"message": "Hello"}
        assert call.input_tokens == 100
        assert call.output_tokens == 50
        assert call.total_tokens == 150
        assert call.model_name == "gpt-4o"

    @pytest.mark.django_db
    def test_mark_failed(self):
        """Test marking a call as failed."""
        from orchestrai_django.models import ServiceCall, CallStatus
        import uuid

        call = ServiceCall.objects.create(
            id=str(uuid.uuid4()),
            service_identity="services.test.example.TestService",
            status=CallStatus.IN_PROGRESS,
        )

        call.mark_failed("Something went wrong")

        assert call.status == CallStatus.FAILED
        assert call.finished_at is not None
        assert call.error == "Something went wrong"

    @pytest.mark.django_db
    def test_to_jsonable(self):
        """Test converting call to JSON-serializable dict."""
        from orchestrai_django.models import ServiceCall, CallStatus
        import uuid

        call = ServiceCall.objects.create(
            id=str(uuid.uuid4()),
            service_identity="services.test.example.TestService",
            status=CallStatus.COMPLETED,
            output_data={"result": "success"},
        )

        data = call.to_jsonable()

        assert data["id"] == call.id
        assert data["service_identity"] == "services.test.example.TestService"
        assert data["status"] == CallStatus.COMPLETED
        assert data["output_data"] == {"result": "success"}


class TestDjangoPydanticAIService:
    """Tests for DjangoPydanticAIService."""

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        from orchestrai_django.components.services import DjangoPydanticAIService
        from orchestrai.prompts import system_prompt

        class TestSchema(BaseModel):
            message: str

        class TestService(DjangoPydanticAIService):
            abstract = False
            response_schema = TestSchema
            model = "openai:gpt-4o"

            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "Test instructions"

        service = TestService(context={"test": "value"})

        assert service.context["test"] == "value"
        assert service.emitter is not None

    def test_service_with_custom_emitter(self):
        """Test that custom emitter is used."""
        from orchestrai_django.components.services import DjangoPydanticAIService

        class TestSchema(BaseModel):
            message: str

        class TestService(DjangoPydanticAIService):
            abstract = False
            response_schema = TestSchema

        mock_emitter = MagicMock()
        service = TestService(emitter=mock_emitter)

        assert service.emitter is mock_emitter


class TestMigrationCompatibility:
    """Tests for backward compatibility during migration."""

    def test_old_and_new_services_coexist(self):
        """Test that old BaseService and new PydanticAIService can coexist."""
        import os
        from orchestrai.components.services import BaseService, PydanticAIService

        class OldService(BaseService):
            abstract = False

            async def arun(self, **ctx):
                return {"type": "old"}

        class NewSchema(BaseModel):
            type: str

        class NewService(PydanticAIService):
            abstract = False
            response_schema = NewSchema
            # Use test model to avoid needing OpenAI API key
            model = "test"

        old = OldService()
        new = NewService()

        assert old is not None
        assert new is not None
        assert hasattr(old, "arun")
        assert hasattr(new, "arun")

    def test_new_service_prompt_methods(self):
        """Test that @system_prompt methods are collected."""
        from orchestrai.components.services import PydanticAIService
        from orchestrai.prompts import system_prompt

        class TestSchema(BaseModel):
            message: str

        class TestService(PydanticAIService):
            abstract = False
            response_schema = TestSchema
            model = "test"

            @system_prompt(weight=100)
            def first(self) -> str:
                return "First"

            @system_prompt(weight=50)
            def second(self) -> str:
                return "Second"

        service = TestService()
        assert len(service._prompt_methods) == 2
        assert service._prompt_methods[0].name == "first"
        assert service._prompt_methods[1].name == "second"
