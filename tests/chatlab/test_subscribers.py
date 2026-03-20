from uuid import uuid4

from django.utils import timezone
import pytest

from orchestrai_django.signals import domain_object_created, service_call_succeeded


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Subscribers")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="subscribers@example.com",
        role=user_role,
    )


@pytest.fixture
def simulation(test_user):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        sim_patient_full_name="Subscriber Patient",
    )


@pytest.fixture
def conversation(simulation):
    from apps.simcore.models import Conversation, ConversationType

    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=ConversationType.objects.get(slug="simulated_patient"),
        display_name="Subscriber Patient",
        display_initials="SP",
    )


@pytest.mark.django_db
def test_service_call_succeeded_marks_message_delivered_and_emits_status_update(
    simulation, conversation, test_user
):
    from apps.chatlab.models import Message, RoleChoices
    from apps.common.models import OutboxEvent
    from orchestrai_django.models import CallStatus, ServiceCall

    message = Message.objects.create(
        simulation=simulation,
        conversation=conversation,
        sender=test_user,
        content="Need help",
        role=RoleChoices.USER,
        is_from_ai=False,
        delivery_status=Message.DeliveryStatus.SENT,
        delivery_retryable=True,
    )
    call = ServiceCall.objects.create(
        id=str(uuid4()),
        service_identity="apps.chatlab.orca.services.patient.GenerateReplyResponse",
        status=CallStatus.COMPLETED,
        context={"simulation_id": simulation.id, "user_msg": message.id},
        correlation_id=str(uuid4()),
        output_data={"ok": True},
    )

    service_call_succeeded.send(
        sender=type(call),
        call=call,
        call_id=call.id,
        attempt=1,
        service_identity=call.service_identity,
        provider_response_id=None,
        output_data=call.output_data,
        context=call.context,
    )

    message.refresh_from_db()
    assert message.delivery_status == Message.DeliveryStatus.DELIVERED
    assert message.delivery_retryable is False

    event = OutboxEvent.objects.filter(
        event_type="message_status_update",
        simulation_id=simulation.id,
    ).latest("created_at")
    assert event.payload["id"] == message.id
    assert event.payload["status"] == Message.DeliveryStatus.DELIVERED
    assert event.payload["retryable"] is False


@pytest.mark.django_db
def test_domain_object_created_emits_ai_message_and_metadata_events(
    simulation, conversation, test_user
):
    from apps.chatlab.models import Message, RoleChoices
    from apps.common.models import OutboxEvent
    from apps.simcore.models import SimulationMetadata
    from orchestrai_django.models import CallStatus, ServiceCall, ServiceCallAttempt

    call = ServiceCall.objects.create(
        id=str(uuid4()),
        service_identity="apps.chatlab.orca.services.patient.GenerateInitialResponse",
        status=CallStatus.COMPLETED,
        context={"simulation_id": simulation.id},
        correlation_id=str(uuid4()),
        output_data={"ok": True},
    )
    attempt = ServiceCallAttempt.objects.create(
        service_call=call,
        attempt=1,
        status="schema_ok",
        received_at=timezone.now(),
    )
    call.context["_service_call_attempt_id"] = attempt.id
    call.save(update_fields=["context"])

    message = Message.objects.create(
        simulation=simulation,
        conversation=conversation,
        sender=test_user,
        content="AI says hello",
        role=RoleChoices.ASSISTANT,
        is_from_ai=True,
        display_name="Subscriber Patient",
        service_call_attempt=attempt,
    )
    metadata = SimulationMetadata.objects.create(
        simulation=simulation,
        key="lab_results_available",
        value="true",
        service_call_attempt=attempt,
    )

    domain_object_created.send(
        sender=type(call),
        call=call,
        call_id=call.id,
        service_identity=call.service_identity,
        domain_obj=message,
        context=call.context,
    )

    message_event = OutboxEvent.objects.filter(
        simulation_id=simulation.id,
        event_type="chat.message_created",
    ).latest("created_at")
    assert message_event.payload["message_id"] == message.id

    refresh_event = OutboxEvent.objects.filter(
        simulation_id=simulation.id,
        event_type="simulation.metadata.results_created",
    ).latest("created_at")
    assert refresh_event.payload["tool"] == "patient_results"
    assert refresh_event.payload["results"][0]["id"] == metadata.id

    alias_event = OutboxEvent.objects.filter(
        simulation_id=simulation.id,
        event_type="metadata.created",
    ).latest("created_at")
    assert alias_event.payload["metadata_id"] == metadata.id
