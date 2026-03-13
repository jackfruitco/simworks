"""Tests for the new declarative persistence framework.

Tests:
- persist_schema() with PatientInitialOutputSchema (messages + metadata auto-mapping)
- persist_schema() with PatientReplyOutputSchema (messages + post_persist hook)
- persist_schema() with PatientResultsOutputSchema (custom persist function)
- persist_schema() with GenerateInitialSimulationFeedback (feedback block)
- MRO merging (mixin __persist__ + schema __persist__)
- Schema without __persist__ returns None
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

from apps.chatlab.models import Message, RoleChoices
from apps.chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
    PatientResultsOutputSchema,
)
from apps.simcore.orca.schemas.feedback import (
    GenerateFeedbackContinuationResponse,
    GenerateInitialSimulationFeedback,
)
from orchestrai_django.persistence import PersistContext, persist_schema


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
    from apps.simcore.models import Simulation

    return Simulation.objects.create(user=user)


@pytest.fixture
def patient_conversation(db, simulation):
    from apps.simcore.models import Conversation, ConversationType

    conv_type, _ = ConversationType.objects.get_or_create(
        slug="simulated_patient",
        defaults={
            "display_name": "Simulated Patient",
            "ai_persona": "patient",
            "locks_with_simulation": True,
            "available_in": ["chatlab"],
            "sort_order": 0,
        },
    )
    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=conv_type,
        display_name=simulation.sim_patient_display_name or "Patient",
        display_initials=simulation.sim_patient_initials or "Pt",
    )


@pytest.fixture
def context(simulation, patient_conversation):
    return PersistContext(
        simulation_id=simulation.id,
        call_id=str(uuid4()),
        extra={"conversation_id": patient_conversation.id},
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPatientInitialPersistence:
    async def test_creates_message_and_metadata(self, context):
        """persist_schema should create Message (from persist_messages) and metadata (auto-mapped)."""
        schema = PatientInitialOutputSchema.model_validate(
            {
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
                "llm_conditions_check": [{"key": "ready", "value": "true"}],
            }
        )

        result = await persist_schema(schema, context)

        # Primary result should be a Message (first from messages list)
        assert isinstance(result, Message)
        assert result.content == "Hello, I have chest pain."
        assert result.role == RoleChoices.ASSISTANT
        assert result.is_from_ai is True
        assert result.sender is not None
        # User model doesn't have 'username' - check email instead
        assert result.sender.email == "system@medsim.local"

        # Check metadata was created as PatientDemographics (polymorphic subclass)
        from apps.simcore.models import PatientDemographics, SimulationMetadata

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
        schema = PatientInitialOutputSchema.model_validate(
            {
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
            }
        )

        await persist_schema(schema, context)

        from apps.simcore.models import SimulationMetadata

        async for meta in SimulationMetadata.objects.filter(simulation_id=context.simulation_id):
            assert "condition_a" not in meta.key
            assert "condition_b" not in meta.key

    async def test_creates_outbox_events_for_messages_and_metadata(self, context):
        """PatientInitialOutputSchema should create outbox events for both messages and metadata."""
        schema = PatientInitialOutputSchema.model_validate(
            {
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
                "llm_conditions_check": [],
            }
        )

        await persist_schema(schema, context)

        # Check message outbox events
        from apps.common.models import OutboxEvent

        message_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="chat.message_created",
        )
        message_event_count = await message_events.acount()
        assert message_event_count == 1  # One message

        msg_event = await message_events.afirst()
        assert msg_event.event_type == "chat.message_created"
        assert msg_event.correlation_id == context.correlation_id
        assert "message_id" in msg_event.payload
        assert "content" in msg_event.payload
        assert msg_event.payload["content"] == "Hello, I have chest pain."

        # Check metadata outbox events
        metadata_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="metadata.created",
        )
        metadata_event_count = await metadata_events.acount()
        assert metadata_event_count == 2  # Two metadata items

        meta_event = await metadata_events.afirst()
        assert meta_event.event_type == "metadata.created"
        assert "metadata_id" in meta_event.payload
        assert "kind" in meta_event.payload
        assert "key" in meta_event.payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPatientReplyPersistence:
    async def test_creates_message_no_metadata(self, context):
        """PatientReplyOutputSchema only persists messages (image_requested is not persisted)."""
        schema = PatientReplyOutputSchema.model_validate(
            {
                "image_requested": False,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "The pain is on my left side."}],
                        "item_meta": [],
                    }
                ],
                "metadata": [],
                "llm_conditions_check": [],
            }
        )

        result = await persist_schema(schema, context)

        assert isinstance(result, Message)
        assert result.content == "The pain is on my left side."

    async def test_post_persist_called_for_image_requested(self, context, caplog):
        """post_persist hook should log when image_requested is True."""
        schema = PatientReplyOutputSchema.model_validate(
            {
                "image_requested": True,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Here is the X-ray."}],
                        "item_meta": [],
                    }
                ],
                "metadata": [],
                "llm_conditions_check": [],
            }
        )

        import logging

        with (
            caplog.at_level(logging.INFO),
            patch("apps.chatlab.tasks.enqueue_generate_patient_image_task"),
        ):
            await persist_schema(schema, context)

        assert any("Image requested" in r.message for r in caplog.records)

    async def test_creates_outbox_events_for_messages(self, context):
        """PatientReplyOutputSchema should create outbox events for messages."""
        schema = PatientReplyOutputSchema.model_validate(
            {
                "image_requested": True,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "The pain is sharp and sudden."}],
                        "item_meta": [],
                    }
                ],
                "metadata": [],
                "llm_conditions_check": [],
            }
        )

        with patch("apps.chatlab.tasks.enqueue_generate_patient_image_task"):
            await persist_schema(schema, context)

        # Check message outbox events
        from apps.common.models import OutboxEvent

        message_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="chat.message_created",
        )
        message_event_count = await message_events.acount()
        assert message_event_count == 1

        msg_event = await message_events.afirst()
        assert msg_event.event_type == "chat.message_created"
        assert msg_event.correlation_id == context.correlation_id
        assert "message_id" in msg_event.payload
        assert "content" in msg_event.payload
        assert "image_requested" in msg_event.payload
        assert msg_event.payload["image_requested"] is True

    async def test_post_persist_enqueues_image_task_for_structured_intent(self, context):
        schema = PatientReplyOutputSchema.model_validate(
            {
                "image_requested": True,
                "image_request": {
                    "requested": True,
                    "prompt": "smartphone photo of red swollen wrist",
                    "caption": "This is how it looks now.",
                    "clinical_focus": "left wrist swelling",
                },
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "I can send a photo now."}],
                        "item_meta": [],
                    }
                ],
                "metadata": [],
                "llm_conditions_check": [],
            }
        )

        with patch("apps.chatlab.tasks.enqueue_generate_patient_image_task") as mock_enqueue:
            await persist_schema(schema, context)

        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        assert kwargs["simulation_id"] == context.simulation_id
        assert kwargs["prompt"] == "smartphone photo of red swollen wrist"

    async def test_post_persist_skips_enqueue_when_not_requested(self, context):
        schema = PatientReplyOutputSchema.model_validate(
            {
                "image_requested": False,
                "image_request": {
                    "requested": False,
                    "prompt": "",
                    "caption": None,
                    "clinical_focus": None,
                },
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "No image needed."}],
                        "item_meta": [],
                    }
                ],
                "metadata": [],
                "llm_conditions_check": [],
            }
        )

        with patch("apps.chatlab.tasks.enqueue_generate_patient_image_task") as mock_enqueue:
            await persist_schema(schema, context)

        mock_enqueue.assert_not_called()

    async def test_reply_metadata_upsert_updates_existing_key(self, context):
        """Reply metadata should upsert by key instead of creating duplicates."""
        from apps.simcore.models import PatientDemographics

        initial = PatientReplyOutputSchema.model_validate(
            {
                "image_requested": False,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "I am 45 years old."}],
                        "item_meta": [],
                    }
                ],
                "metadata": [
                    {"kind": "patient_demographics", "key": "age", "value": "45"},
                ],
                "llm_conditions_check": [],
            }
        )
        await persist_schema(initial, context)

        update = PatientReplyOutputSchema.model_validate(
            {
                "image_requested": False,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Actually I just turned 46."}],
                        "item_meta": [],
                    }
                ],
                "metadata": [
                    {"kind": "patient_demographics", "key": "age", "value": "46"},
                ],
                "llm_conditions_check": [],
            }
        )
        await persist_schema(update, context)

        count = await PatientDemographics.objects.filter(
            simulation_id=context.simulation_id,
            key="age",
        ).acount()
        assert count == 1

        age = await PatientDemographics.objects.aget(
            simulation_id=context.simulation_id,
            key="age",
        )
        assert age.value == "46"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPatientResultsPersistence:
    async def test_creates_metadata_from_results(self, context):
        """PatientResultsOutputSchema persists metadata via custom persist function."""
        schema = PatientResultsOutputSchema.model_validate(
            {
                "metadata": [
                    {
                        "kind": "generic",
                        "key": "communication_score",
                        "value": "Good communication skills",
                    }
                ],
                "llm_conditions_check": [],
            }
        )

        await persist_schema(schema, context)

        from apps.simcore.models import SimulationMetadata

        meta = await SimulationMetadata.objects.filter(simulation_id=context.simulation_id).afirst()
        assert meta is not None
        assert meta.key == "communication_score"
        assert meta.value == "Good communication skills"

    async def test_creates_outbox_events_for_metadata(self, context):
        """PatientResultsOutputSchema should create outbox events for metadata."""
        schema = PatientResultsOutputSchema.model_validate(
            {
                "metadata": [
                    {
                        "kind": "generic",
                        "key": "bedside_manner_score",
                        "value": "Excellent bedside manner",
                    },
                    {
                        "kind": "generic",
                        "key": "history_taking_score",
                        "value": "Thorough history taking",
                    },
                ],
                "llm_conditions_check": [],
            }
        )

        await persist_schema(schema, context)

        # Check metadata outbox events
        from apps.common.models import OutboxEvent

        metadata_events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="metadata.created",
        )
        metadata_event_count = await metadata_events.acount()
        assert metadata_event_count == 2  # Two metadata items

        meta_event = await metadata_events.afirst()
        assert meta_event.event_type == "metadata.created"
        assert meta_event.correlation_id == context.correlation_id
        assert "metadata_id" in meta_event.payload
        assert "kind" in meta_event.payload
        assert "key" in meta_event.payload
        assert "value" in meta_event.payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestHotwashPersistence:
    async def test_creates_feedback_records(self, context):
        """GenerateInitialSimulationFeedback should create multiple SimulationFeedback records."""
        schema = GenerateInitialSimulationFeedback.model_validate(
            {
                "llm_conditions_check": [],
                "metadata": {
                    "correct_diagnosis": True,
                    "correct_treatment_plan": False,
                    "patient_experience": 4,
                    "overall_feedback": "Good job overall!",
                },
            }
        )

        await persist_schema(schema, context)

        from apps.simcore.models import SimulationFeedback

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

    async def test_creates_outbox_events_for_websocket_broadcast(self, context):
        """GenerateInitialSimulationFeedback should create outbox events for WebSocket delivery."""
        schema = GenerateInitialSimulationFeedback.model_validate(
            {
                "llm_conditions_check": [],
                "metadata": {
                    "correct_diagnosis": True,
                    "correct_treatment_plan": False,
                    "patient_experience": 4,
                    "overall_feedback": "Good job overall!",
                },
            }
        )

        await persist_schema(schema, context)

        # Check that outbox events were created
        from apps.common.models import OutboxEvent

        events = OutboxEvent.objects.filter(
            simulation_id=context.simulation_id,
            event_type="feedback.created",
        )
        event_count = await events.acount()

        # Should have 4 events (one per feedback item)
        assert event_count == 4

        # Check event structure
        event = await events.afirst()
        assert event.event_type == "feedback.created"
        assert event.correlation_id == context.correlation_id
        assert "feedback_id" in event.payload
        assert "key" in event.payload
        assert "value" in event.payload

        # Check idempotency keys are unique
        idempotency_keys = [e.idempotency_key async for e in events]
        assert len(idempotency_keys) == len(set(idempotency_keys)), (
            "Idempotency keys should be unique"
        )

        # Check all idempotency keys start with event type
        for key in idempotency_keys:
            assert key.startswith("feedback.created:"), (
                f"Idempotency key should start with event type: {key}"
            )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestFeedbackContinuationPersistence:
    async def test_continuation_feedback_upserts_single_key(self, context):
        """Continuation feedback should upsert direct-answer key."""
        from apps.simcore.models import SimulationFeedback

        first = GenerateFeedbackContinuationResponse.model_validate(
            {
                "llm_conditions_check": [],
                "metadata": {"direct_answer": "Start with a concise summary of your differential."},
            }
        )
        await persist_schema(first, context)

        second = GenerateFeedbackContinuationResponse.model_validate(
            {
                "llm_conditions_check": [],
                "metadata": {
                    "direct_answer": "Prioritize time-course and red-flag questions first."
                },
            }
        )
        await persist_schema(second, context)

        count = await SimulationFeedback.objects.filter(
            simulation_id=context.simulation_id,
            key="hotwash_continuation_direct_answer",
        ).acount()
        assert count == 1

        row = await SimulationFeedback.objects.aget(
            simulation_id=context.simulation_id,
            key="hotwash_continuation_direct_answer",
        )
        assert row.value == "Prioritize time-course and red-flag questions first."


class TestMROMerging:
    def test_mixin_persist_inherited_by_child(self):
        """PatientInitialOutputSchema should inherit messages persistence from mixin."""
        from apps.chatlab.orca.persisters import persist_messages
        from orchestrai_django.persistence.engine import _merge_persist_from_mro

        persist_map = _merge_persist_from_mro(PatientInitialOutputSchema)

        # Should have both messages (from mixin) and metadata (from schema)
        assert "messages" in persist_map
        assert persist_map["messages"] is persist_messages
        assert "metadata" in persist_map
        assert persist_map["metadata"] is None  # auto-mapped

    def test_child_does_not_need_to_redeclare_mixin_fields(self):
        """PatientReplyOutputSchema should get messages persistence from mixin without redeclaring."""
        from apps.chatlab.orca.persisters import persist_messages
        from orchestrai_django.persistence.engine import _merge_persist_from_mro

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
