from datetime import UTC, datetime, timedelta
import json

from django.http import QueryDict
from django.urls import reverse
import pytest

from apps.common.models import OutboxEvent
from apps.common.outbox.event_types import PATIENT_PULSE_CREATED, PATIENT_VITAL_UPDATED
from apps.common.outbox.outbox import order_outbox_queryset
from apps.common.watch import parse_watch_page_state, serialize_outbox_events
from apps.trainerlab.models import RuntimeEvent
from apps.trainerlab.services import create_session
from orchestrai_django.models import ServiceCall


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Watch View Test Role")


@pytest.fixture
def chatlab_owner(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="chatlab-owner@example.com",
        role=user_role,
        is_staff=True,
    )


@pytest.fixture
def chatlab_admin(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="chatlab-admin@example.com",
        role=user_role,
        is_staff=True,
    )


@pytest.fixture
def trainer_member(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="trainer-member@example.com",
        role=user_role,
        is_staff=True,
    )


@pytest.fixture
def trainer_non_member(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="trainer-non-member@example.com",
        role=user_role,
        is_staff=True,
    )


@pytest.fixture
def trainerlab_lab(db):
    from apps.accounts.models import Lab

    lab, _ = Lab.objects.get_or_create(
        slug="trainerlab",
        defaults={"display_name": "TrainerLab", "is_active": True},
    )
    return lab


@pytest.fixture
def trainer_membership(trainer_member):
    """Grant entitlement-based TrainerLab access on the user's personal account."""
    from apps.accounts.services import get_personal_account_for_user
    from apps.billing.catalog import ProductCode
    from apps.billing.models import Entitlement

    personal_account = get_personal_account_for_user(trainer_member)
    return Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:trainerlab-go",
        scope_type=Entitlement.ScopeType.USER,
        subject_user=trainer_member,
        product_code=ProductCode.TRAINERLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
        portable_across_accounts=True,
    )


@pytest.fixture
def chat_simulation(chatlab_owner):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=chatlab_owner,
        diagnosis="Appendicitis",
        chief_complaint="Abdominal pain",
        sim_patient_full_name="Casey Chat",
    )


@pytest.fixture
def trainer_simulation(trainer_member):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=trainer_member,
        diagnosis="Pneumothorax",
        chief_complaint="Shortness of breath",
        sim_patient_full_name="Taylor Trainer",
    )


@pytest.mark.django_db
def test_parse_watch_page_state_and_event_grouping(chat_simulation):
    state = parse_watch_page_state(
        QueryDict(
            "events_page=2&events_page_size=50&events_filter=simulation&events_q=pulse"
            "&events_sort=asc&sc_page=3&sc_page_size=100"
        )
    )

    assert state.events_page == 2
    assert state.events_page_size == 50
    assert state.events_filter == "simulation"
    assert state.events_q == "pulse"
    assert state.events_sort == "asc"
    assert state.sc_page == 3
    assert state.sc_page_size == 100

    event_types = [
        PATIENT_PULSE_CREATED,
        PATIENT_PULSE_CREATED,
        PATIENT_VITAL_UPDATED,
        PATIENT_PULSE_CREATED,
    ]
    created_event_ids = []
    for index, event_type in enumerate(event_types, start=1):
        event = OutboxEvent.objects.create(
            simulation_id=chat_simulation.id,
            event_type=event_type,
            payload={"index": index},
            idempotency_key=f"watch-grouping:{index}",
        )
        created_event_ids.append(event.id)

    serialized = serialize_outbox_events(
        order_outbox_queryset(OutboxEvent.objects.filter(id__in=created_event_ids))
    )

    assert [event["sequence_group_id"] for event in serialized] == [1, 1, 2, 3]


@pytest.mark.django_db
def test_chatlab_watch_view_uses_query_params_for_initial_state(
    client, chatlab_owner, chat_simulation
):
    client.force_login(chatlab_owner)

    response = client.get(
        reverse("chatlab:watch_simulation", kwargs={"simulation_id": chat_simulation.id}),
        {
            "events_page": 2,
            "events_page_size": 50,
            "events_filter": "simulation",
            "events_q": "pulse",
            "events_sort": "asc",
        },
    )

    assert response.status_code == 200
    watch_state = response.context["watch_state"]
    assert watch_state.events_page == 2
    assert watch_state.events_page_size == 50
    assert watch_state.events_filter == "simulation"
    assert watch_state.events_q == "pulse"
    assert watch_state.events_sort == "asc"
    assert response.context["realtime_transport"] == "websocket"
    assert response.context["stream_url"] == "/ws/v1/chatlab/"


@pytest.mark.django_db
def test_chatlab_service_calls_partial_paginates_and_preserves_query_params(
    client, chatlab_owner, chat_simulation
):
    client.force_login(chatlab_owner)

    for index in range(60):
        ServiceCall.objects.create(
            service_identity="chatlab.patient",
            related_object_id=str(chat_simulation.id),
            input={"index": index},
            output_data={"index": index},
        )

    response = client.get(
        reverse("chatlab:watch_service_calls", kwargs={"simulation_id": chat_simulation.id}),
        {
            "sc_page": 2,
            "sc_page_size": 25,
            "events_filter": "simulation",
            "events_q": "pulse",
        },
    )

    assert response.status_code == 200
    assert response.context["service_calls_page"].number == 2
    assert response.context["service_calls_page"].paginator.per_page == 25

    content = response.content.decode()
    assert "Page 2 of 3" in content
    assert "events_filter=simulation" in content
    assert "events_q=pulse" in content


@pytest.mark.django_db
def test_service_call_actions_only_show_download_for_full_call(
    client, chatlab_owner, chat_simulation
):
    client.force_login(chatlab_owner)

    ServiceCall.objects.create(
        service_identity="chatlab.patient",
        related_object_id=str(chat_simulation.id),
        input={"prompt": "hello"},
        output_data={"message": "world"},
    )

    response = client.get(
        reverse("chatlab:watch_service_calls", kwargs={"simulation_id": chat_simulation.id})
    )

    content = response.content.decode()
    assert content.count("Download JSON") == 3
    assert content.count("Copy JSON") == 3


@pytest.mark.django_db
def test_chatlab_watch_button_reflects_owner_access(
    client, chatlab_owner, chatlab_admin, chat_simulation
):
    watch_url = reverse("chatlab:watch_simulation", kwargs={"simulation_id": chat_simulation.id})
    run_url = reverse("chatlab:run_simulation", kwargs={"simulation_id": chat_simulation.id})

    client.force_login(chatlab_owner)
    owner_response = client.get(watch_url)
    assert owner_response.status_code == 200
    owner_content = owner_response.content.decode()
    assert run_url in owner_content
    assert "Go to simulation" in owner_content

    client.force_login(chatlab_admin)
    admin_response = client.get(watch_url)
    assert admin_response.status_code == 200
    admin_content = admin_response.content.decode()
    assert f'href="{run_url}"' not in admin_content
    assert "You do not have access to this simulation run view." in admin_content


@pytest.mark.django_db
def test_trainerlab_watch_button_and_run_view_reflect_membership(
    client, trainer_member, trainer_non_member, trainer_membership, trainer_simulation
):
    watch_url = reverse(
        "trainerlab:watch_simulation", kwargs={"simulation_id": trainer_simulation.id}
    )
    run_url = reverse("trainerlab:run_simulation", kwargs={"simulation_id": trainer_simulation.id})

    client.force_login(trainer_member)
    member_watch = client.get(watch_url)
    assert member_watch.status_code == 200
    assert f'href="{run_url}"' in member_watch.content.decode()
    assert client.get(run_url).status_code == 200

    client.force_login(trainer_non_member)
    non_member_watch = client.get(watch_url)
    assert non_member_watch.status_code == 200
    non_member_content = non_member_watch.content.decode()
    assert f'href="{run_url}"' not in non_member_content
    assert "You do not have access to this simulation run view." in non_member_content
    assert client.get(run_url).status_code == 403


@pytest.mark.django_db
def test_trainerlab_watch_view_renders_truth_snapshot_and_cache_sections(
    client, trainer_member, trainer_membership
):
    session = create_session(
        user=trainer_member,
        scenario_spec={},
        directives="",
        modifiers=[],
    )

    client.force_login(trainer_member)
    response = client.get(
        reverse(
            "trainerlab:watch_simulation",
            kwargs={"simulation_id": session.simulation_id},
        )
    )

    assert response.status_code == 200
    assert response.context["realtime_transport"] == "sse"
    assert response.context["watch_detail_partial"] == "trainerlab/partials/watch_details.html"
    assert response.context["trainer_watch_snapshot_cache_json"]
    content = response.content.decode()
    assert "TrainerLab Truth And Snapshots" in content
    assert "ScenarioState Summary" in content
    assert "RuntimeState Summary" in content
    assert "ScenarioSnapshot" in content
    assert "RuntimeSnapshot" in content
    assert "EventTimeline" in content
    assert "SnapshotCache" in content
    assert '"status": "disabled"' in response.context["trainer_watch_snapshot_cache_json"]


@pytest.mark.django_db
def test_trainerlab_watch_view_uses_chronological_event_timeline(
    client, trainer_member, trainer_membership
):
    session = create_session(
        user=trainer_member,
        scenario_spec={},
        directives="",
        modifiers=[],
    )
    base_time = datetime(2030, 1, 1, tzinfo=UTC)
    baseline_events = RuntimeEvent.objects.filter(session=session).count()

    for sequence in range(3):
        runtime_event = RuntimeEvent.objects.create(
            session=session,
            simulation=session.simulation,
            event_type="trainerlab.runtime.note",
            payload={"sequence": sequence},
        )
        RuntimeEvent.objects.filter(pk=runtime_event.pk).update(
            created_at=base_time + timedelta(seconds=sequence)
        )

    client.force_login(trainer_member)
    response = client.get(
        reverse(
            "trainerlab:watch_simulation",
            kwargs={"simulation_id": session.simulation_id},
        )
    )

    assert response.status_code == 200
    timeline = json.loads(response.context["trainer_watch_event_timeline_json"])
    assert timeline["total_events"] == baseline_events + 3
    assert [
        event["payload"]["sequence"]
        for event in timeline["events"]
        if "sequence" in event["payload"]
    ] == [0, 1, 2]
