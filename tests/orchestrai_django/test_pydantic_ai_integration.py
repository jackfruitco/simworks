"""
Tests for Django Pydantic AI integration.

These tests verify the DjangoBaseService and related Django components.
"""

from unittest.mock import MagicMock

from pydantic import BaseModel
import pytest


class TestServiceCallModel:
    """Tests for the new ServiceCall model."""

    @pytest.mark.django_db
    def test_service_call_creation(self):
        """Test creating a ServiceCall record."""
        import uuid

        from orchestrai_django.models import CallStatus, ServiceCall

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
        import uuid

        from orchestrai_django.models import CallStatus, ServiceCall

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
        import uuid

        from orchestrai_django.models import CallStatus, ServiceCall

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
        import uuid

        from orchestrai_django.models import CallStatus, ServiceCall

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
        import uuid

        from orchestrai_django.models import CallStatus, ServiceCall

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


class TestDjangoBaseService:
    """Tests for DjangoBaseService."""

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        from orchestrai.prompts import system_prompt
        from orchestrai_django.components.services import DjangoBaseService

        class TestSchema(BaseModel):
            message: str

        class TestService(DjangoBaseService):
            abstract = False
            response_schema = TestSchema
            model = "openai-responses:gpt-5-nano"

            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "Test instructions"

        service = TestService(context={"test": "value"})

        assert service.context["test"] == "value"
        assert service.emitter is not None

    def test_service_with_custom_emitter(self):
        """Test that custom emitter is used."""
        from orchestrai_django.components.services import DjangoBaseService

        class TestSchema(BaseModel):
            message: str

        class TestService(DjangoBaseService):
            abstract = False
            response_schema = TestSchema

        mock_emitter = MagicMock()
        service = TestService(emitter=mock_emitter)

        assert service.emitter is mock_emitter



class TestBaseService:
    """Tests for BaseService (consolidated Pydantic AI-based service)."""

    def test_service_has_task_descriptor(self):
        """Test that BaseService has a task descriptor."""
        from orchestrai.components.services import BaseService

        # task should be a descriptor that returns a proxy
        assert hasattr(BaseService, "task")

        class TestSchema(BaseModel):
            message: str

        class TestService(BaseService):
            abstract = False
            response_schema = TestSchema
            model = "test"

        # Accessing task on the class should return a proxy
        proxy = TestService.task
        assert proxy is not None
        assert hasattr(proxy, "using")

    def test_prompt_methods_are_collected(self):
        """Test that @system_prompt methods are collected."""
        from orchestrai.components.services import BaseService
        from orchestrai.prompts import system_prompt

        class TestSchema(BaseModel):
            message: str

        class TestService(BaseService):
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
