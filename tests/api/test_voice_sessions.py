"""Tests for VoiceLab session broker endpoints."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import Client, override_settings
import pytest

from api.v1.auth import create_access_token


def _attach_chatlab_session(simulation):
    from apps.chatlab.models import ChatSession

    ChatSession.objects.get_or_create(simulation=simulation)
    return simulation


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Voice Session Tester")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="voice@example.com",
        role=user_role,
    )


@pytest.fixture(autouse=True)
def chatlab_access(test_user):
    from apps.accounts.services import get_personal_account_for_user
    from apps.billing.catalog import ProductCode
    from apps.billing.models import Entitlement

    personal_account = get_personal_account_for_user(test_user)
    return Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:voice-tests",
        scope_type=Entitlement.ScopeType.USER,
        subject_user=test_user,
        product_code=ProductCode.CHATLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
        portable_across_accounts=True,
    )


@pytest.fixture
def auth_client(test_user):
    token = create_access_token(test_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def patient_type(db):
    from apps.simcore.models import ConversationType

    conversation_type, _ = ConversationType.objects.get_or_create(
        slug="simulated_patient",
        defaults={
            "display_name": "Patient",
            "ai_persona": "patient",
        },
    )
    return conversation_type


@pytest.fixture
def simulation(test_user):
    from apps.simcore.models import Simulation

    simulation = Simulation.objects.create(
        user=test_user,
        diagnosis="Test Diagnosis",
        chief_complaint="Chest pain",
        sim_patient_full_name="Jane Doe",
    )
    return _attach_chatlab_session(simulation)


@pytest.fixture
def conversation(simulation, patient_type):
    from apps.simcore.models import Conversation

    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=patient_type,
        display_name="Jane Doe",
        display_initials="JD",
    )


def _provider_start(expires_at=None):
    from apps.chatlab.voice import VoiceSessionStart

    expires_at = expires_at or datetime.now(UTC) + timedelta(minutes=5)
    return VoiceSessionStart(
        client_secret={"value": "ek_test", "expires_at": int(expires_at.timestamp())},
        session_config={"type": "realtime", "model": "gpt-realtime-test"},
        realtime_url="https://api.openai.test/v1/realtime/client_secrets",
        calls_url="https://api.openai.test/v1/realtime/calls",
        expires_at=expires_at,
        provider_session_id="realtime_session_123",
        provider_metadata={"id": "realtime_session_123"},
    )


@pytest.mark.django_db
class TestVoiceSessions:
    def test_start_voice_session_returns_ephemeral_connection_material(
        self,
        auth_client,
        simulation,
        conversation,
    ):
        from apps.chatlab.models import VoiceSession
        from apps.common.models import OutboxEvent
        from apps.common.outbox import event_types

        with patch(
            "apps.chatlab.voice.OpenAIRealtimeSessionBroker.start_session",
            return_value=_provider_start(),
        ) as start_session:
            response = auth_client.post(
                f"/api/v1/simulations/{simulation.pk}/voice/session/",
                data={
                    "conversation_id": conversation.pk,
                    "transport": "webrtc",
                    "model": "gpt-realtime-test",
                    "voice": "verse",
                    "client_metadata": {"app_version": "1.0"},
                },
                content_type="application/json",
            )

        assert response.status_code == 201
        data = response.json()
        assert data["simulation_id"] == simulation.pk
        assert data["conversation_id"] == conversation.pk
        assert data["status"] == "active"
        assert data["transport"] == "webrtc"
        assert data["provider"] == "openai"
        assert data["provider_session_id"] == "realtime_session_123"
        assert data["client_secret"]["value"] == "ek_test"
        assert data["calls_url"].endswith("/realtime/calls")

        start_session.assert_called_once()
        voice_session = VoiceSession.objects.get(pk=data["id"])
        assert voice_session.status == VoiceSession.Status.ACTIVE
        assert voice_session.client_metadata == {"app_version": "1.0"}
        assert voice_session.provider_metadata == {"id": "realtime_session_123"}
        assert OutboxEvent.objects.filter(
            simulation_id=simulation.pk,
            event_type=event_types.VOICE_SESSION_CREATED,
            payload__voice_session_id=voice_session.pk,
        ).exists()

    def test_start_voice_session_defaults_to_patient_conversation(
        self,
        auth_client,
        simulation,
        patient_type,
    ):
        from apps.simcore.models import Conversation

        with patch(
            "apps.chatlab.voice.OpenAIRealtimeSessionBroker.start_session",
            return_value=_provider_start(),
        ):
            response = auth_client.post(
                f"/api/v1/simulations/{simulation.pk}/voice/session/",
                data={},
                content_type="application/json",
            )

        assert response.status_code == 201
        conversation = Conversation.objects.get(
            simulation=simulation, conversation_type=patient_type
        )
        assert response.json()["conversation_id"] == conversation.pk

    def test_start_voice_session_rejects_terminal_simulation_before_provider_call(
        self,
        auth_client,
        simulation,
        conversation,
    ):
        from apps.chatlab.models import VoiceSession
        from apps.simcore.models import Simulation

        simulation.status = Simulation.SimulationStatus.COMPLETED
        simulation.save(update_fields=["status"])

        with patch("apps.chatlab.voice.OpenAIRealtimeSessionBroker.start_session") as start_session:
            response = auth_client.post(
                f"/api/v1/simulations/{simulation.pk}/voice/session/",
                data={"conversation_id": conversation.pk},
                content_type="application/json",
            )

        assert response.status_code == 400
        start_session.assert_not_called()
        assert not VoiceSession.objects.filter(simulation=simulation).exists()

    @override_settings(OPENAI_API_KEY=None)
    def test_start_voice_session_marks_failed_when_provider_not_configured(
        self,
        auth_client,
        simulation,
        conversation,
    ):
        from apps.chatlab.models import VoiceSession
        from apps.common.models import OutboxEvent
        from apps.common.outbox import event_types

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/voice/session/",
            data={"conversation_id": conversation.pk},
            content_type="application/json",
        )

        assert response.status_code == 503
        voice_session = VoiceSession.objects.get(simulation=simulation)
        assert voice_session.status == VoiceSession.Status.FAILED
        assert voice_session.last_error_code == "provider_not_configured"
        assert OutboxEvent.objects.filter(
            simulation_id=simulation.pk,
            event_type=event_types.VOICE_SESSION_UPDATED,
            payload__voice_session_id=voice_session.pk,
            payload__status="failed",
        ).exists()

    def test_end_voice_session_marks_session_ended(
        self, auth_client, simulation, conversation, test_user
    ):
        from apps.chatlab.models import VoiceSession
        from apps.common.models import OutboxEvent
        from apps.common.outbox import event_types

        voice_session = VoiceSession.objects.create(
            simulation=simulation,
            conversation=conversation,
            created_by=test_user,
            status=VoiceSession.Status.ACTIVE,
            transport=VoiceSession.Transport.WEBRTC,
            model_name="gpt-realtime-test",
            voice_name="verse",
        )

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/end/",
        )

        assert response.status_code == 200
        voice_session.refresh_from_db()
        assert voice_session.status == VoiceSession.Status.ENDED
        assert voice_session.ended_at is not None
        assert response.json()["status"] == "ended"
        assert OutboxEvent.objects.filter(
            simulation_id=simulation.pk,
            event_type=event_types.VOICE_SESSION_UPDATED,
            payload__voice_session_id=voice_session.pk,
            payload__status="ended",
        ).exists()
