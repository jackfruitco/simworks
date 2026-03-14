from unittest.mock import patch

import pytest

from orchestrai_django.signals import ai_response_failed


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Failure Signals")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="signals@example.com",
        role=user_role,
    )


@pytest.fixture
def simulation(test_user):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        sim_patient_full_name="Signal Patient",
    )


@pytest.fixture
def conversation(simulation):
    from apps.simcore.models import Conversation, ConversationType

    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=ConversationType.objects.get(slug="simulated_patient"),
        display_name="Signal Patient",
        display_initials="SP",
    )


@pytest.mark.django_db
class TestFailureSignals:
    @patch("apps.common.outbox.poke_drain_sync")
    def test_terminal_generate_initial_response_failure_marks_simulation_failed_and_emits_event(
        self, _mock_poke, simulation
    ):
        from apps.common.models import OutboxEvent
        from orchestrai_django.models import CallStatus, ServiceCall

        call = ServiceCall.objects.create(
            service_identity="apps.chatlab.orca.services.patient.GenerateInitialResponse",
            status=CallStatus.FAILED,
            context={"simulation_id": simulation.id},
            error="Provider timed out",
        )

        ai_response_failed.send(
            sender=self.__class__,
            call_id=call.id,
            error="Provider timed out",
            reason_code="provider_timeout",
        )

        simulation.refresh_from_db()
        assert simulation.status == simulation.SimulationStatus.FAILED
        assert simulation.terminal_reason_code == "initial_generation_provider_timeout"

        event = OutboxEvent.objects.filter(
            event_type="simulation.state_changed",
            simulation_id=simulation.id,
        ).latest("created_at")
        assert event.payload["status"] == simulation.SimulationStatus.FAILED
        assert event.payload["terminal_reason_code"] == "initial_generation_provider_timeout"
        assert event.payload["retryable"] is True

    @patch("apps.common.outbox.poke_drain_sync")
    def test_terminal_reply_failure_marks_message_failed_and_emits_status_update(
        self, _mock_poke, simulation, conversation, test_user
    ):
        from apps.chatlab.models import Message, RoleChoices
        from apps.common.models import OutboxEvent
        from orchestrai_django.models import CallStatus, ServiceCall

        message = Message.objects.create(
            simulation=simulation,
            conversation=conversation,
            sender=test_user,
            content="Help",
            role=RoleChoices.USER,
            is_from_ai=False,
            delivery_status=Message.DeliveryStatus.SENT,
            delivery_retryable=True,
        )
        call = ServiceCall.objects.create(
            service_identity="apps.chatlab.orca.services.patient.GenerateReplyResponse",
            status=CallStatus.FAILED,
            context={"simulation_id": simulation.id, "user_msg": message.id},
            error="Provider failed",
        )

        ai_response_failed.send(
            sender=self.__class__,
            call_id=call.id,
            error="Provider failed",
            reason_code="provider_transient_error",
        )

        message.refresh_from_db()
        assert message.delivery_status == Message.DeliveryStatus.FAILED
        assert message.delivery_error_code == "provider_transient_error"
        assert message.delivery_retryable is True

        event = OutboxEvent.objects.filter(
            event_type="message_status_update",
            simulation_id=simulation.id,
        ).latest("created_at")
        assert event.payload["id"] == message.id
        assert event.payload["status"] == Message.DeliveryStatus.FAILED
        assert event.payload["retryable"] is True
