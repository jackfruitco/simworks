"""Tests for chatlab patient persistence handlers.

Tests:
- Message creation with correct sender and role
- Metadata extraction and persistence
- Idempotency behavior
- Error handling
"""

import pytest
from uuid import uuid4

from orchestrai.types import Response
from chatlab.orca.persist.patient import (
    PatientInitialPersistence,
    PatientReplyPersistence,
    PatientResultsPersistence,
)
from chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
    PatientResultsOutputSchema,
)
from chatlab.models import Message, RoleChoices


@pytest.fixture
def sample_initial_response_data():
    """Sample structured data for PatientInitialOutputSchema."""
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello, I'm experiencing chest pain."}],
                "item_meta": [],
            }
        ],
        "metadata": [
            {"key": "patient_name", "value": "John Smith"},
            {"key": "age", "value": "45"},
        ],
        "llm_conditions_check": [
            {"key": "ready_for_questions", "value": "true"}
        ],
    }


@pytest.fixture
def sample_reply_response_data():
    """Sample structured data for PatientReplyOutputSchema."""
    return {
        "image_requested": False,
        "messages": [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "The pain is in my left side."}],
                "item_meta": [],
            }
        ],
        "llm_conditions_check": [],
    }


class TestPatientInitialPersistenceHandler:
    """Tests for PatientInitialPersistence handler."""

    def test_handler_has_correct_schema(self):
        """Verify handler is configured with correct schema."""
        assert PatientInitialPersistence.schema == PatientInitialOutputSchema

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_persist_creates_message_with_system_user(
        self, sample_initial_response_data
    ):
        """Verify persistence creates Message with system user as sender."""
        from simulation.models import Simulation
        from accounts.models import CustomUser as User, UserRole

        # Create test role and user
        role, _ = await UserRole.objects.aget_or_create(title="Test")
        user = await User.objects.acreate(
            username=f"test_user_{uuid4().hex[:8]}",
            email=f"test_{uuid4().hex[:8]}@test.com",
            role=role,
        )
        sim = await Simulation.objects.acreate(user=user)

        # Create response
        response = Response(
            namespace="chatlab",
            correlation_id=uuid4(),
            structured_data=sample_initial_response_data,
            execution_metadata={
                "schema_identity": PatientInitialOutputSchema.identity.as_str
            },
            context={"simulation_id": sim.id, "call_id": str(uuid4())},
        )

        # Persist
        handler = PatientInitialPersistence()
        message = await handler.persist(response)

        # Verify Message created
        assert message is not None
        assert message.id is not None
        assert message.content == "Hello, I'm experiencing chest pain."
        assert message.is_from_ai is True
        assert message.role == RoleChoices.ASSISTANT

        # Verify sender is system user (not None)
        assert message.sender is not None
        assert message.sender.username == "System"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_persist_uses_correct_role_enum(self, sample_initial_response_data):
        """Verify persistence uses RoleChoices.ASSISTANT, not string."""
        from simulation.models import Simulation
        from accounts.models import CustomUser as User, UserRole

        role, _ = await UserRole.objects.aget_or_create(title="Test")
        user = await User.objects.acreate(
            username=f"test_user_{uuid4().hex[:8]}",
            email=f"test_{uuid4().hex[:8]}@test.com",
            role=role,
        )
        sim = await Simulation.objects.acreate(user=user)

        response = Response(
            namespace="chatlab",
            correlation_id=uuid4(),
            structured_data=sample_initial_response_data,
            execution_metadata={
                "schema_identity": PatientInitialOutputSchema.identity.as_str
            },
            context={"simulation_id": sim.id, "call_id": str(uuid4())},
        )

        handler = PatientInitialPersistence()
        message = await handler.persist(response)

        # Verify role is the enum value "A", not string "assistant"
        assert message.role == "A"
        assert message.role == RoleChoices.ASSISTANT

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_persist_idempotency(self, sample_initial_response_data):
        """Verify calling persist twice with same call_id returns same Message."""
        from simulation.models import Simulation
        from accounts.models import CustomUser as User, UserRole

        role, _ = await UserRole.objects.aget_or_create(title="Test")
        user = await User.objects.acreate(
            username=f"test_user_{uuid4().hex[:8]}",
            email=f"test_{uuid4().hex[:8]}@test.com",
            role=role,
        )
        sim = await Simulation.objects.acreate(user=user)

        call_id = str(uuid4())
        response = Response(
            namespace="chatlab",
            correlation_id=uuid4(),
            structured_data=sample_initial_response_data,
            execution_metadata={
                "schema_identity": PatientInitialOutputSchema.identity.as_str
            },
            context={"simulation_id": sim.id, "call_id": call_id},
        )

        handler = PatientInitialPersistence()

        # First persist
        message1 = await handler.persist(response)

        # Second persist (should be idempotent)
        message2 = await handler.persist(response)

        # Should return same message
        assert message1.id == message2.id

        # Should only have one Message in DB for this simulation
        message_count = await Message.objects.filter(simulation=sim).acount()
        assert message_count == 1

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_persist_missing_simulation_raises(self, sample_initial_response_data):
        """Verify ValueError raised when simulation_id missing from context."""
        response = Response(
            namespace="chatlab",
            correlation_id=uuid4(),
            structured_data=sample_initial_response_data,
            execution_metadata={
                "schema_identity": PatientInitialOutputSchema.identity.as_str
            },
            context={},  # Missing simulation_id
        )

        handler = PatientInitialPersistence()

        with pytest.raises(ValueError, match="simulation_id"):
            await handler.persist(response)


class TestPatientReplyPersistenceHandler:
    """Tests for PatientReplyPersistence handler."""

    def test_handler_has_correct_schema(self):
        """Verify handler is configured with correct schema."""
        assert PatientReplyPersistence.schema == PatientReplyOutputSchema

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_persist_creates_message_with_system_user(
        self, sample_reply_response_data
    ):
        """Verify persistence creates Message with system user as sender."""
        from simulation.models import Simulation
        from accounts.models import CustomUser as User, UserRole

        role, _ = await UserRole.objects.aget_or_create(title="Test")
        user = await User.objects.acreate(
            username=f"test_user_{uuid4().hex[:8]}",
            email=f"test_{uuid4().hex[:8]}@test.com",
            role=role,
        )
        sim = await Simulation.objects.acreate(user=user)

        response = Response(
            namespace="chatlab",
            correlation_id=uuid4(),
            structured_data=sample_reply_response_data,
            execution_metadata={
                "schema_identity": PatientReplyOutputSchema.identity.as_str
            },
            context={"simulation_id": sim.id, "call_id": str(uuid4())},
        )

        handler = PatientReplyPersistence()
        message = await handler.persist(response)

        # Verify Message created
        assert message is not None
        assert message.content == "The pain is in my left side."
        assert message.is_from_ai is True
        assert message.role == RoleChoices.ASSISTANT

        # Verify sender is system user
        assert message.sender is not None
        assert message.sender.username == "System"


class TestPatientInitialPersistenceLlmConditionsCheck:
    """Tests verifying llm_conditions_check is NOT persisted."""

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_llm_conditions_check_not_persisted_to_message(self):
        """Verify llm_conditions_check field is NOT persisted to Message or any related model.

        The llm_conditions_check field is an internal LLM workflow field that should:
        - Be present in the schema for structured output validation
        - NOT be stored in the database
        - Be silently ignored during persistence
        """
        from simulation.models import Simulation, SimulationMetadata
        from accounts.models import CustomUser as User, UserRole

        # Create test fixtures
        role, _ = await UserRole.objects.aget_or_create(title="Test")
        user = await User.objects.acreate(
            username=f"test_user_{uuid4().hex[:8]}",
            email=f"test_{uuid4().hex[:8]}@test.com",
            role=role,
        )
        sim = await Simulation.objects.acreate(user=user)

        # Create response with explicit llm_conditions_check data
        response_data = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Test message"}],
                    "item_meta": [],
                }
            ],
            "metadata": [
                {"key": "patient_name", "value": "Test Patient"},
            ],
            "llm_conditions_check": [
                {"key": "condition_a", "value": "met"},
                {"key": "condition_b", "value": "not_met"},
                {"key": "ready_for_next_phase", "value": "true"},
            ],
        }

        response = Response(
            namespace="chatlab",
            correlation_id=uuid4(),
            structured_data=response_data,
            execution_metadata={
                "schema_identity": PatientInitialOutputSchema.identity.as_str
            },
            context={"simulation_id": sim.id, "call_id": str(uuid4())},
        )

        # Persist
        handler = PatientInitialPersistence()
        message = await handler.persist(response)

        # Verify Message was created
        assert message is not None
        assert message.id is not None

        # Verify Message does NOT have any llm_conditions_check related fields
        # Check all message fields for any conditions-related data
        message_fields = [f.name for f in message._meta.get_fields()]
        assert "llm_conditions_check" not in message_fields
        assert "llm_conditions" not in message_fields
        assert "conditions_check" not in message_fields

        # Verify Message content does not contain conditions data
        assert "condition_a" not in (message.content or "")
        assert "condition_b" not in (message.content or "")

        # Verify no SimulationMetadata with conditions data was created
        metadata_count = await SimulationMetadata.objects.filter(simulation=sim).acount()
        if metadata_count > 0:
            async for metadata in SimulationMetadata.objects.filter(simulation=sim):
                # Check that metadata key is not related to llm_conditions_check
                if hasattr(metadata, 'key'):
                    assert "condition_a" not in (metadata.key or "")
                    assert "llm_conditions_check" not in (metadata.key or "")

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_llm_conditions_check_with_empty_list_still_works(self):
        """Verify persistence works when llm_conditions_check is empty list."""
        from simulation.models import Simulation
        from accounts.models import CustomUser as User, UserRole

        role, _ = await UserRole.objects.aget_or_create(title="Test")
        user = await User.objects.acreate(
            username=f"test_user_{uuid4().hex[:8]}",
            email=f"test_{uuid4().hex[:8]}@test.com",
            role=role,
        )
        sim = await Simulation.objects.acreate(user=user)

        # Response with empty llm_conditions_check
        response_data = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Empty conditions test"}],
                    "item_meta": [],
                }
            ],
            "metadata": [],
            "llm_conditions_check": [],  # Empty list
        }

        response = Response(
            namespace="chatlab",
            correlation_id=uuid4(),
            structured_data=response_data,
            execution_metadata={
                "schema_identity": PatientInitialOutputSchema.identity.as_str
            },
            context={"simulation_id": sim.id, "call_id": str(uuid4())},
        )

        handler = PatientInitialPersistence()
        message = await handler.persist(response)

        # Should still work normally
        assert message is not None
        assert message.content == "Empty conditions test"


class TestPatientResultsPersistenceHandler:
    """Tests for PatientResultsPersistence handler."""

    def test_handler_has_correct_schema(self):
        """Verify handler is configured with correct schema."""
        assert PatientResultsPersistence.schema == PatientResultsOutputSchema
