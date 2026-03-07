"""Tests for Django Pydantic AI integration."""

from unittest.mock import MagicMock

from pydantic import BaseModel
import pytest


class TestServiceCallModel:
    """Tests for the ServiceCall model."""

    @pytest.mark.django_db
    def test_service_call_creation(self):
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
        from orchestrai.instructions import BaseInstruction
        from orchestrai_django.components.services import DjangoBaseService
        from orchestrai_django.decorators import orca

        class TestSchema(BaseModel):
            message: str

        @orca.instruction(order=10)
        class TestInstruction(BaseInstruction):
            instruction = "Test instructions"

        class TestService(TestInstruction, DjangoBaseService):
            abstract = False
            response_schema = TestSchema
            model = "openai-responses:gpt-5-nano"

        service = TestService(context={"test": "value"})

        assert service.context["test"] == "value"
        assert service.emitter is not None

    def test_service_with_custom_emitter(self):
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
        from orchestrai.components.services import BaseService

        assert hasattr(BaseService, "task")

        class TestSchema(BaseModel):
            message: str

        class TestService(BaseService):
            abstract = False
            response_schema = TestSchema
            model = "test"

        proxy = TestService.task
        assert proxy is not None
        assert hasattr(proxy, "using")

    def test_instruction_classes_are_collected(self):
        from orchestrai.components.services import BaseService
        from orchestrai.instructions import BaseInstruction
        from orchestrai_django.decorators import orca

        class TestSchema(BaseModel):
            message: str

        @orca.instruction(order=10)
        class FirstInstruction(BaseInstruction):
            instruction = "First"

        @orca.instruction(order=50)
        class SecondInstruction(BaseInstruction):
            instruction = "Second"

        class TestService(FirstInstruction, SecondInstruction, BaseService):
            abstract = False
            response_schema = TestSchema
            model = "test"

        service = TestService()
        assert len(service._instruction_classes) == 2
        assert service._instruction_classes[0] is FirstInstruction
        assert service._instruction_classes[1] is SecondInstruction


def test_orca_namespace_available_on_all_import_paths():
    from orchestrai import orca as orchestrai_orca
    from orchestrai.decorators import orca as decorators_orca
    from orchestrai_django import orca as orchestrai_django_orca
    from orchestrai_django.decorators import orca as django_decorators_orca

    assert orchestrai_orca.service is decorators_orca.service
    assert orchestrai_orca.instruction is decorators_orca.instruction
    assert orchestrai_django_orca.service is django_decorators_orca.service
    assert orchestrai_django_orca.instruction is django_decorators_orca.instruction
