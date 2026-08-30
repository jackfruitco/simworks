"""Tests for VoiceLab session broker endpoints."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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


def _provider_start(
    expires_at=None,
    *,
    provider_session_id="realtime_session_123",
    calls_url="https://api.openai.test/v1/realtime/calls",
    websocket_url=None,
):
    from apps.chatlab.voice import VoiceSessionStart

    expires_at = expires_at or datetime.now(UTC) + timedelta(minutes=5)
    return VoiceSessionStart(
        client_secret={"value": "ek_test", "expires_at": int(expires_at.timestamp())},
        session_config={"type": "realtime", "model": "gpt-realtime-test"},
        realtime_url="https://api.openai.test/v1/realtime/client_secrets",
        calls_url=calls_url,
        websocket_url=websocket_url,
        expires_at=expires_at,
        provider_session_id=provider_session_id,
        provider_metadata={"id": provider_session_id},
    )


def _active_voice_session(simulation, conversation, test_user):
    from apps.chatlab.models import VoiceSession

    return VoiceSession.objects.create(
        simulation=simulation,
        conversation=conversation,
        created_by=test_user,
        status=VoiceSession.Status.ACTIVE,
        transport=VoiceSession.Transport.WEBRTC,
        model_name="gpt-realtime-test",
        voice_name="verse",
    )


@pytest.mark.django_db
class TestVoiceSessions:
    def test_realtime_session_config_uses_shared_voice_instructions_and_tools(
        self,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import Message, RoleChoices
        from apps.chatlab.voice import build_realtime_session_config

        Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="I have pain in my chest.",
            role=RoleChoices.USER,
            display_name="Learner",
        )
        Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Can you describe the pain?",
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
            display_name="Jane Doe",
        )

        config = build_realtime_session_config(
            simulation=simulation,
            conversation=conversation,
            model="gpt-realtime-test",
            voice="verse",
        )

        assert config["audio"]["input"]["transcription"]["model"]
        assert config["audio"]["output"]["voice"] == "verse"
        assert "Recent text conversation for continuity" not in config["instructions"]
        assert "I have pain in my chest." not in config["instructions"]
        assert "Voice Turn Behavior" in config["instructions"]
        assert "Do not reveal or name the diagnosis" in config["instructions"]
        assert {tool["name"] for tool in config["tools"]} >= {
            "patient_history",
            "patient_results",
            "simulation_metadata",
            "sign_lab_orders",
        }

    def test_realtime_bootstrap_items_preserve_canonical_message_order(
        self,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import Message, RoleChoices
        from apps.chatlab.voice import build_realtime_bootstrap_items

        Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="I have pain in my chest.",
            role=RoleChoices.USER,
        )
        Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Tell me more about it.",
            role=RoleChoices.ASSISTANT,
            is_from_ai=True,
        )

        items = build_realtime_bootstrap_items(conversation)

        assert [item["item"]["role"] for item in items] == ["user", "assistant"]
        assert [item["item"]["content"][0]["text"] for item in items] == [
            "I have pain in my chest.",
            "Tell me more about it.",
        ]
        assert items[0]["type"] == "conversation.item.create"
        assert items[1]["item"]["content"][0]["type"] == "text"

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

    @override_settings(
        OPENAI_API_KEY="sk-test",
        VOICELAB_OPENAI_WEBSOCKET_URL="wss://api.openai.test/v1/realtime",
    )
    def test_realtime_broker_supports_websocket_transport(
        self,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import VoiceSession
        from apps.chatlab.voice import OpenAIRealtimeSessionBroker

        response = MagicMock()
        response.json.return_value = {
            "id": "realtime_session_ws_123",
            "client_secret": {
                "value": "ek_test_ws",
                "expires_at": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            },
        }
        response.raise_for_status.return_value = None

        with patch("apps.chatlab.voice.httpx.post", return_value=response):
            start = OpenAIRealtimeSessionBroker().start_session(
                user=test_user,
                simulation=simulation,
                conversation=conversation,
                transport=VoiceSession.Transport.WEBSOCKET,
                model="gpt-realtime-test",
                voice="verse",
            )

        assert start.client_secret["value"] == "ek_test_ws"
        assert start.calls_url is None
        assert start.websocket_url == "wss://api.openai.test/v1/realtime"

    @override_settings(OPENAI_API_KEY=None)
    def test_realtime_broker_uses_configured_orchestrai_openai_key(
        self,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import VoiceSession
        from apps.chatlab.voice import OpenAIRealtimeSessionBroker

        response = MagicMock()
        response.json.return_value = {
            "id": "realtime_session_123",
            "client_secret": {"value": "ek_test"},
        }
        response.raise_for_status.return_value = None

        with (
            patch("apps.chatlab.voice.get_api_key", return_value="sk-orca-test"),
            patch("apps.chatlab.voice.httpx.post", return_value=response) as post,
        ):
            OpenAIRealtimeSessionBroker().start_session(
                user=test_user,
                simulation=simulation,
                conversation=conversation,
                transport=VoiceSession.Transport.WEBRTC,
                model="gpt-realtime-test",
                voice="verse",
            )

        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-orca-test"

    def test_start_voice_session_is_idempotent_for_client_key(
        self,
        auth_client,
        simulation,
        conversation,
    ):
        from apps.chatlab.models import VoiceSession

        with patch(
            "apps.chatlab.voice.OpenAIRealtimeSessionBroker.start_session",
            side_effect=[
                _provider_start(provider_session_id="realtime_session_123"),
                _provider_start(provider_session_id="realtime_session_456"),
            ],
        ) as start_session:
            first = auth_client.post(
                f"/api/v1/simulations/{simulation.pk}/voice/session/",
                data={
                    "conversation_id": conversation.pk,
                    "transport": "webrtc",
                    "model": "gpt-realtime-test",
                    "voice": "verse",
                    "idempotency_key": "voice-start-1",
                },
                content_type="application/json",
            )
            second = auth_client.post(
                f"/api/v1/simulations/{simulation.pk}/voice/session/",
                data={
                    "conversation_id": conversation.pk,
                    "transport": "webrtc",
                    "model": "gpt-realtime-test",
                    "voice": "verse",
                    "idempotency_key": "voice-start-1",
                },
                content_type="application/json",
            )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert second.json()["provider_session_id"] == "realtime_session_456"
        assert VoiceSession.objects.filter(simulation=simulation).count() == 1
        assert start_session.call_count == 2

    def test_start_voice_session_rejects_idempotency_key_parameter_mismatch(
        self,
        auth_client,
        simulation,
        conversation,
    ):
        from apps.chatlab.models import VoiceSession

        with patch(
            "apps.chatlab.voice.OpenAIRealtimeSessionBroker.start_session",
            return_value=_provider_start(),
        ) as start_session:
            first = auth_client.post(
                f"/api/v1/simulations/{simulation.pk}/voice/session/",
                data={
                    "conversation_id": conversation.pk,
                    "transport": "webrtc",
                    "voice": "verse",
                    "idempotency_key": "voice-start-conflict",
                },
                content_type="application/json",
            )
            second = auth_client.post(
                f"/api/v1/simulations/{simulation.pk}/voice/session/",
                data={
                    "conversation_id": conversation.pk,
                    "transport": "websocket",
                    "voice": "verse",
                    "idempotency_key": "voice-start-conflict",
                },
                content_type="application/json",
            )

        assert first.status_code == 201
        assert second.status_code == 409
        assert VoiceSession.objects.filter(simulation=simulation).count() == 1
        assert start_session.call_count == 1

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

    def test_persist_user_voice_transcript_creates_chat_message(
        self,
        auth_client,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent
        from apps.common.outbox import event_types

        voice_session = _active_voice_session(simulation, conversation, test_user)

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/transcripts/",
            data={
                "role": "user",
                "transcript": "  I feel short of breath.  ",
                "provider_item_id": "item-user-1",
                "provider_response_id": "response-user-1",
                "metadata": {"turn": 3},
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["persisted"] is True
        assert data["message"]["role"] == "user"
        assert data["message"]["content"] == "I feel short of breath."

        message = Message.objects.get(pk=data["message"]["id"])
        assert message.role == RoleChoices.USER
        assert message.is_from_ai is False
        assert message.provider_response_id == "response-user-1"
        receipt = voice_session.transcript_receipts.get(message=message)
        assert receipt.metadata == {
            "turn": 3,
            "source": "voice",
            "voice_session_id": voice_session.pk,
            "provider_item_id": "item-user-1",
            "provider_response_id": "response-user-1",
            "provider_event_id": None,
        }
        assert OutboxEvent.objects.filter(
            simulation_id=simulation.pk,
            event_type=event_types.MESSAGE_CREATED,
            payload__message_id=message.pk,
        ).exists()

    def test_persist_assistant_voice_transcript_emits_chat_message_event(
        self,
        auth_client,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent
        from apps.common.outbox import event_types

        voice_session = _active_voice_session(simulation, conversation, test_user)

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/transcripts/",
            data={
                "role": "assistant",
                "transcript": "It started about an hour ago.",
                "provider_response_id": "response-assistant-1",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["message"]["role"] == "assistant"

        message = Message.objects.get(pk=data["message"]["id"])
        assert message.role == RoleChoices.ASSISTANT
        assert message.is_from_ai is True
        assert message.provider_response_id == "response-assistant-1"
        assert OutboxEvent.objects.filter(
            simulation_id=simulation.pk,
            event_type=event_types.MESSAGE_CREATED,
            payload__message_id=message.pk,
            payload__status="completed",
        ).exists()

    def test_persist_voice_transcript_is_idempotent_for_provider_item(
        self,
        auth_client,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import Message, VoiceTranscriptReceipt

        voice_session = _active_voice_session(simulation, conversation, test_user)
        url = (
            f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/transcripts/"
        )

        first = auth_client.post(
            url,
            data={
                "role": "user",
                "transcript": "The pain is sharp.",
                "provider_item_id": "item-duplicate-1",
            },
            content_type="application/json",
        )
        second = auth_client.post(
            url,
            data={
                "role": "user",
                "transcript": "The pain is sharp.",
                "provider_item_id": "item-duplicate-1",
            },
            content_type="application/json",
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["persisted"] is False
        assert first.json()["message"]["id"] == second.json()["message"]["id"]
        assert Message.objects.filter(provider_response_id="item-duplicate-1").count() == 0
        assert (
            VoiceTranscriptReceipt.objects.filter(
                voice_session=voice_session,
                provider_message_id="item-duplicate-1",
            ).count()
            == 1
        )

    def test_persist_voice_transcript_requires_active_session(
        self,
        auth_client,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import VoiceSession

        voice_session = _active_voice_session(simulation, conversation, test_user)
        voice_session.status = VoiceSession.Status.ENDED
        voice_session.save(update_fields=["status"])

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/transcripts/",
            data={"role": "user", "transcript": "Hello"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Voice session is not active"

    def test_execute_voice_tool_call_returns_patient_history(
        self,
        auth_client,
        simulation,
        conversation,
        test_user,
    ):
        from apps.simcore.models import PatientHistory

        voice_session = _active_voice_session(simulation, conversation, test_user)
        PatientHistory.objects.create(
            simulation=simulation,
            key="asthma",
            value="Childhood asthma",
        )

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/tool-calls/",
            data={
                "tool_call_id": "call-history-1",
                "name": "patient_history",
                "arguments": {},
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tool_call_id"] == "call-history-1"
        assert data["name"] == "patient_history"
        assert data["output"]["name"] == "patient_history"
        assert data["output"]["data"][0]["value"] == "Childhood asthma"

    @patch("apps.chatlab.orca.services.lab_orders.GenerateLabResults.task")
    def test_execute_voice_tool_call_submits_lab_orders(
        self,
        mock_lab_results_task,
        auth_client,
        simulation,
        conversation,
        test_user,
    ):
        from apps.chatlab.models import VoiceToolCall

        mock_enqueue = MagicMock()
        mock_enqueue.aenqueue = AsyncMock(return_value="call-id-voice-1")
        mock_lab_results_task.using.return_value = mock_enqueue

        voice_session = _active_voice_session(simulation, conversation, test_user)

        response = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/tool-calls/",
            data={
                "tool_call_id": "call-orders-1",
                "name": "sign_lab_orders",
                "arguments": {"orders": [" CBC ", "CBC", "CMP"]},
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tool_call_id"] == "call-orders-1"
        assert data["name"] == "sign_lab_orders"
        assert data["output"] == {
            "status": "accepted",
            "call_id": "call-id-voice-1",
            "orders": ["CBC", "CMP"],
        }
        context = mock_lab_results_task.using.call_args.kwargs["context"]
        assert context["simulation_id"] == simulation.id
        assert context["orders"] == ["CBC", "CMP"]
        assert context["correlation_id"]

        duplicate = auth_client.post(
            f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/tool-calls/",
            data={
                "tool_call_id": "call-orders-1",
                "name": "sign_lab_orders",
                "arguments": {"orders": [" CBC ", "CBC", "CMP"]},
            },
            content_type="application/json",
        )

        assert duplicate.status_code == 200
        assert duplicate.json()["output"] == data["output"]
        assert mock_lab_results_task.using.call_count == 1
        assert (
            VoiceToolCall.objects.filter(
                voice_session=voice_session,
                tool_call_id="call-orders-1",
                status=VoiceToolCall.Status.COMPLETED,
            ).count()
            == 1
        )

    @patch("apps.chatlab.orca.services.lab_orders.GenerateLabResults.task")
    def test_execute_voice_tool_call_rejects_idempotency_parameter_mismatch(
        self,
        mock_lab_results_task,
        auth_client,
        simulation,
        conversation,
        test_user,
    ):
        mock_enqueue = MagicMock()
        mock_enqueue.aenqueue = AsyncMock(return_value="call-id-voice-1")
        mock_lab_results_task.using.return_value = mock_enqueue

        voice_session = _active_voice_session(simulation, conversation, test_user)
        url = f"/api/v1/simulations/{simulation.pk}/voice/sessions/{voice_session.uuid}/tool-calls/"

        first = auth_client.post(
            url,
            data={
                "tool_call_id": "call-orders-conflict",
                "name": "sign_lab_orders",
                "arguments": {"orders": ["CBC"]},
            },
            content_type="application/json",
        )
        second = auth_client.post(
            url,
            data={
                "tool_call_id": "call-orders-conflict",
                "name": "sign_lab_orders",
                "arguments": {"orders": ["CMP"]},
            },
            content_type="application/json",
        )

        assert first.status_code == 200
        assert second.status_code == 409
        assert mock_lab_results_task.using.call_count == 1
