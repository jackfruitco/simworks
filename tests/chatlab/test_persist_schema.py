"""Tests for the new declarative persistence framework.

Tests:
- persist_schema() with PatientInitialOutputSchema (messages + metadata auto-mapping)
- persist_schema() with PatientReplyOutputSchema (messages + post_persist hook)
- persist_schema() with PatientResultsOutputSchema (custom persist function)
- persist_schema() with GenerateInitialSimulationFeedback (feedback block)
- MRO merging (mixin __persist__ + schema __persist__)
- Schema without __persist__ returns None
"""

import pytest
from uuid import uuid4

from orchestrai_django.persistence import PersistContext, persist_schema
from chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
    PatientResultsOutputSchema,
)
from simulation.orca.schemas.feedback import GenerateInitialSimulationFeedback
from chatlab.models import Message, RoleChoices


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Persist")


@pytest.fixture
def user(db, user_role):
    from apps.accounts.models import User

    return User.objects.create_user(
        email=f"test_{uuid4().hex[:8]}@test.com",
        password="testpass123",
        role=user_role,
    )


@pytest.fixture
def simulation(db, user):
    from simulation.models import Simulation

    return Simulation.objects.create(user=user)


@pytest.fixture
def context(simulation):
    return PersistContext(
        simulation_id=simulation.id,
        call_id=str(uuid4()),
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPatientInitialPersistence:
    async def test_creates_message_and_metadata(self, context):
        """persist_schema should create Message (from persist_messages) and metadata (auto-mapped)."""
        schema = PatientInitialOutputSchema.model_validate({
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello, I have chest pain."}],
                    "item_meta": [],
                }
            ],
            "metadata": [
                {"kind": "patient_demographics", "key": "patient_name", "value": "John Smith"},
                {"kind": "patient_demographics", "key": "age", "value": "45"},
            ],
            "llm_conditions_check": [
                {"key": "ready", "value": "true"}
            ],
        })

        result = await persist_schema(schema, context)

        # Primary result should be a Message (first from messages list)
        assert isinstance(result, Message)
        assert result.content == "Hello, I have chest pain."
        assert result.role == RoleChoices.ASSISTANT
        assert result.is_from_ai is True
        assert result.sender is not None
        # User model doesn't have 'username' - check email instead
        assert result.sender.email == "system@simworks.local"

        # Check metadata was created as PatientDemographics (polymorphic subclass)
        from simulation.models import SimulationMetadata, PatientDemographics
        metadata_count = await SimulationMetadata.objects.filter(
            simulation_id=context.simulation_id
        ).acount()
        assert metadata_count == 2

        # Verify polymorphic type is PatientDemographics
        demographics_count = await PatientDemographics.objects.filter(
            simulation_id=context.simulation_id
        ).acount()
        assert demographics_count == 2

    async def test_llm_conditions_check_not_persisted(self, context):
        """llm_conditions_check should NOT be persisted."""
        schema = PatientInitialOutputSchema.model_validate({
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Test message content"}],
                    "item_meta": [],
                }
            ],
            "metadata": [],
            "llm_conditions_check": [
                {"key": "condition_a", "value": "met"},
                {"key": "condition_b", "value": "not_met"},
            ],
        })

        await persist_schema(schema, context)

        from simulation.models import SimulationMetadata
        async for meta in SimulationMetadata.objects.filter(simulation_id=context.simulation_id):
            assert "condition_a" not in meta.key
            assert "condition_b" not in meta.key


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPatientReplyPersistence:
    async def test_creates_message_no_metadata(self, context):
        """PatientReplyOutputSchema only persists messages (image_requested is not persisted)."""
        schema = PatientReplyOutputSchema.model_validate({
            "image_requested": False,
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "The pain is on my left side."}],
                    "item_meta": [],
                }
            ],
            "llm_conditions_check": [],
        })

        result = await persist_schema(schema, context)

        assert isinstance(result, Message)
        assert result.content == "The pain is on my left side."

    async def test_post_persist_called_for_image_requested(self, context, caplog):
        """post_persist hook should log when image_requested is True."""
        schema = PatientReplyOutputSchema.model_validate({
            "image_requested": True,
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Here is the X-ray."}],
                    "item_meta": [],
                }
            ],
            "llm_conditions_check": [],
        })

        import logging
        with caplog.at_level(logging.INFO):
            await persist_schema(schema, context)

        assert any("Image requested" in r.message for r in caplog.records)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPatientResultsPersistence:
    async def test_creates_metadata_from_results(self, context):
        """PatientResultsOutputSchema persists metadata via custom persist function."""
        schema = PatientResultsOutputSchema.model_validate({
            "metadata": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Good communication skills"}],
                    "item_meta": [{"key": "key", "value": "communication_score"}],
                }
            ],
            "llm_conditions_check": [],
        })

        result = await persist_schema(schema, context)

        from simulation.models import SimulationMetadata
        meta = await SimulationMetadata.objects.filter(
            simulation_id=context.simulation_id
        ).afirst()
        assert meta is not None
        assert meta.key == "communication_score"
        assert meta.value == "Good communication skills"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestHotwashPersistence:
    async def test_creates_feedback_records(self, context):
        """GenerateInitialSimulationFeedback should create multiple SimulationFeedback records."""
        schema = GenerateInitialSimulationFeedback.model_validate({
            "llm_conditions_check": [],
            "metadata": {
                "correct_diagnosis": True,
                "correct_treatment_plan": False,
                "patient_experience": 4,
                "overall_feedback": "Good job overall!",
            },
        })

        result = await persist_schema(schema, context)

        from simulation.models import SimulationFeedback
        feedback_count = await SimulationFeedback.objects.filter(
            simulation_id=context.simulation_id
        ).acount()
        assert feedback_count == 4

        # Check specific values
        diag = await SimulationFeedback.objects.aget(
            simulation_id=context.simulation_id,
            key="hotwash_correct_diagnosis",
        )
        assert diag.value == "True"

        overall = await SimulationFeedback.objects.aget(
            simulation_id=context.simulation_id,
            key="hotwash_overall_feedback",
        )
        assert overall.value == "Good job overall!"


class TestMROMerging:
    def test_mixin_persist_inherited_by_child(self):
        """PatientInitialOutputSchema should inherit messages persistence from mixin."""
        from orchestrai_django.persistence.engine import _merge_persist_from_mro
        from chatlab.orca.persisters import persist_messages

        persist_map = _merge_persist_from_mro(PatientInitialOutputSchema)

        # Should have both messages (from mixin) and metadata (from schema)
        assert "messages" in persist_map
        assert persist_map["messages"] is persist_messages
        assert "metadata" in persist_map
        assert persist_map["metadata"] is None  # auto-mapped

    def test_child_does_not_need_to_redeclare_mixin_fields(self):
        """PatientReplyOutputSchema should get messages persistence from mixin without redeclaring."""
        from orchestrai_django.persistence.engine import _merge_persist_from_mro
        from chatlab.orca.persisters import persist_messages

        persist_map = _merge_persist_from_mro(PatientReplyOutputSchema)

        assert "messages" in persist_map
        assert persist_map["messages"] is persist_messages


@pytest.mark.asyncio
class TestSchemaWithoutPersist:
    async def test_returns_none_for_schema_without_persist(self):
        """Schema with no __persist__ should return None."""
        from pydantic import BaseModel, Field

        class NoopSchema(BaseModel):
            value: str = Field(...)

        schema = NoopSchema(value="test")
        ctx = PersistContext(simulation_id=1, call_id="noop")

        result = await persist_schema(schema, ctx)
        assert result is None
