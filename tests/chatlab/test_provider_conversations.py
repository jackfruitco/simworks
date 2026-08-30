"""Tests for durable Responses conversation identity and message synchronization."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Provider Conversation Tester")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="provider-conversation@example.com",
        role=user_role,
    )


@pytest.fixture
def conversation(db, test_user):
    from apps.simcore.models import Conversation, ConversationType, Simulation

    conversation_type, _ = ConversationType.objects.get_or_create(
        slug="simulated_patient",
        defaults={"display_name": "Patient", "ai_persona": "patient"},
    )
    simulation = Simulation.objects.create(
        user=test_user,
        diagnosis="Test diagnosis",
        chief_complaint="Chest pain",
        sim_patient_full_name="Jane Doe",
    )
    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=conversation_type,
        display_name="Jane Doe",
    )


def _response(*, status_code=200, payload=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload or {}
    response.raise_for_status.return_value = None
    return response


@pytest.mark.django_db
class TestProviderConversationSync:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_patient_text_context_uses_conversation_not_previous_response(self, conversation):
        from apps.chatlab.ai.conversations import ProviderConversation
        from apps.chatlab.orca.services.patient import GenerateReplyResponse

        service = GenerateReplyResponse(
            context={
                "simulation_id": conversation.simulation_id,
                "conversation_id": conversation.pk,
                "previous_response_id": "resp_old",
            }
        )
        with (
            patch(
                "apps.chatlab.ai.conversations.ensure_provider_conversation",
                return_value=ProviderConversation("conv_123"),
            ),
            patch("apps.chatlab.ai.conversations.sync_messages_to_provider"),
        ):
            await service._aprepare_patient_provider_context()

        assert service.context["model_settings"] == {"openai_conversation_id": "conv_123"}
        assert "previous_response_id" not in service.context["model_settings"]
        assert "previous_response_id" not in service.context
        assert "previous_provider_response_id" not in service.context

    @pytest.fixture(autouse=True)
    def configured_provider(self, settings):
        settings.OPENAI_API_KEY = "sk-test"

    def test_ensure_creates_one_provider_conversation(self, conversation):
        from apps.chatlab.ai.conversations import ensure_provider_conversation

        with patch(
            "apps.chatlab.ai.conversations.httpx.post",
            return_value=_response(payload={"id": "conv_123"}),
        ) as post:
            first = ensure_provider_conversation(conversation)
            second = ensure_provider_conversation(conversation)

        assert first.id == "conv_123"
        assert second.id == "conv_123"
        assert post.call_count == 1
        conversation.refresh_from_db()
        assert conversation.provider_conversation_id == "conv_123"

    def test_sync_appends_ordered_messages_once(self, conversation, test_user):
        from apps.chatlab.ai.conversations import sync_messages_to_provider
        from apps.chatlab.models import Message, ProviderConversationItem, RoleChoices

        Message.objects.create(
            simulation=conversation.simulation,
            conversation=conversation,
            sender=test_user,
            content="I have chest pain.",
            role=RoleChoices.USER,
        )
        second = Message.objects.create(
            simulation=conversation.simulation,
            conversation=conversation,
            content="When did it start?",
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
        )
        with patch(
            "apps.chatlab.ai.conversations.httpx.post",
            side_effect=[
                _response(payload={"id": "conv_123"}),
                _response(payload={"data": [{"id": "item_user"}]}),
                _response(payload={"data": [{"id": "item_assistant"}]}),
            ],
        ) as post:
            assert sync_messages_to_provider(conversation) == second.pk
            assert sync_messages_to_provider(conversation) == second.pk

        assert post.call_count == 3
        assert ProviderConversationItem.objects.count() == 2
        conversation.refresh_from_db()
        assert conversation.provider_sync_cursor == second.pk
        assert conversation.provider_sync_status == "synced"
        append_calls = post.call_args_list[1:]
        assert [call.kwargs["json"]["items"][0]["role"] for call in append_calls] == [
            "user",
            "assistant",
        ]

    def test_voice_boundary_sync_uses_branch_cursor(self, conversation, test_user):
        from apps.chatlab.ai.conversations import sync_voice_session_to_provider
        from apps.chatlab.models import Message, RoleChoices, VoiceSession

        conversation.provider_conversation_id = "conv_existing"
        conversation.provider_sync_cursor = 10
        conversation.save(update_fields=["provider_conversation_id", "provider_sync_cursor"])
        old_message = Message.objects.create(
            simulation=conversation.simulation,
            conversation=conversation,
            sender=test_user,
            content="Old text",
            role=RoleChoices.USER,
        )
        new_message = Message.objects.create(
            simulation=conversation.simulation,
            conversation=conversation,
            sender=test_user,
            content="Voice transcript",
            role=RoleChoices.USER,
        )
        session = VoiceSession.objects.create(
            simulation=conversation.simulation,
            conversation=conversation,
            created_by=test_user,
            status=VoiceSession.Status.ENDED,
            responses_sync_cursor=old_message.pk,
        )

        with patch(
            "apps.chatlab.ai.conversations.httpx.post",
            return_value=_response(payload={"data": [{"id": "item_voice"}]}),
        ) as post:
            assert sync_voice_session_to_provider(session) == new_message.pk

        assert post.call_count == 1
        session.refresh_from_db()
        assert session.responses_sync_cursor == new_message.pk
        assert session.responses_sync_status == "synced"

    def test_voice_sync_failure_retains_pending_state(self, conversation, test_user):
        from apps.chatlab.ai.conversations import (
            ProviderConversationError,
            sync_voice_session_to_provider,
        )
        from apps.chatlab.models import VoiceSession

        session = VoiceSession.objects.create(
            simulation=conversation.simulation,
            conversation=conversation,
            created_by=test_user,
            status=VoiceSession.Status.ENDED,
        )
        with (
            patch(
                "apps.chatlab.ai.conversations.sync_messages_to_provider",
                side_effect=ProviderConversationError("provider unavailable"),
            ),
            pytest.raises(ProviderConversationError),
        ):
            sync_voice_session_to_provider(session)

        session.refresh_from_db()
        assert session.responses_sync_status == "pending"
        assert session.responses_sync_error == "provider unavailable"

    def test_text_and_voice_render_shared_patient_safety_but_only_text_has_schema(self):
        from apps.chatlab.ai.context import PatientRuntimeContext
        from apps.chatlab.ai.instructions import (
            render_text_patient_instructions,
            render_voice_patient_instructions,
        )

        context = PatientRuntimeContext(
            simulation_id=1,
            conversation_id=1,
            patient_name="Jane Doe",
            patient_full_name="Jane Doe",
            chief_complaint="Chest pain",
            conversation_name="Jane Doe",
            persona="patient",
        )

        text_instructions = render_text_patient_instructions(context)
        voice_instructions = render_voice_patient_instructions(context)

        assert "Do not reveal or name the diagnosis" in text_instructions
        assert "Do not reveal or name the diagnosis" in voice_instructions
        assert "### Schema Contract" in text_instructions
        assert "### Schema Contract" not in voice_instructions
        assert "Voice Turn Behavior" in voice_instructions
