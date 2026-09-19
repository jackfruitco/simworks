"""Patient-first dashboard projection contract tests."""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
import pytest

from api.v1.schemas.trainerlab import TrainerRestViewModelOut
from apps.accounts.models import UserRole
from apps.trainerlab.models import (
    EventSource,
    HeartRate,
    PatientStatusState,
    SessionStatus,
)
from apps.trainerlab.services import create_session
from apps.trainerlab.viewmodels import (
    build_trainer_rest_view_model,
    load_trainer_engine_aggregate,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def session(django_user_model):
    role = UserRole.objects.create(title="Phase IV instructor")
    user = django_user_model.objects.create_user(
        email="phase4@example.com",
        password="testpass123",
        role=role,
    )
    session = create_session(user=user, scenario_spec={}, directives="", modifiers=[])
    session.status = SessionStatus.RUNNING
    session.run_started_at = timezone.now()
    session.runtime_state_json = {
        "active_elapsed_seconds": 30,
        "active_elapsed_anchor_started_at": timezone.now().isoformat(),
        "ai_plan": {
            "summary": "Watch for worsening respiratory effort.",
            "rationale": "The chest injury remains untreated.",
            "upcoming_changes": ["SpO2 may fall", "Work of breathing may increase"],
            "monitoring_focus": ["Respiratory effort", "SpO2"],
        },
    }
    session.save()
    return session


def test_dashboard_projection_is_compact_deterministic_and_query_free(session):
    PatientStatusState.objects.create(
        simulation=session.simulation,
        source=EventSource.SYSTEM,
        avpu="verbal",
        respiratory_distress=True,
        impending_pneumothorax=True,
    )
    HeartRate.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        min_value=112,
        max_value=112,
        lock_value=True,
    )
    aggregate = load_trainer_engine_aggregate(session=session)

    with CaptureQueriesContext(connection) as queries:
        view_model = build_trainer_rest_view_model(aggregate)

    assert len(queries) == 0
    assert view_model.presentation.primary_cue == "Watch for worsening respiratory effort."
    assert view_model.presentation.monitoring_focus == ["Respiratory effort", "SpO2"]
    assert view_model.presentation.held_vital_types == ["heart_rate"]
    assert [item.code for item in view_model.presentation.attention_items] == [
        "respiratory_distress",
        "impending_pneumothorax",
    ]
    assert view_model.presentation.capabilities.lifecycle_actions == ["pause", "stop"]
    assert view_model.presentation.capabilities.can_record_learner_action is True
    assert view_model.presentation.capabilities.can_tick_ai is True


@pytest.mark.parametrize(
    ("status", "actions", "can_mutate", "can_annotate", "can_view_debrief"),
    [
        (SessionStatus.SEEDING, [], False, False, False),
        (SessionStatus.SEEDED, ["start", "stop"], True, True, False),
        (SessionStatus.RUNNING, ["pause", "stop"], True, True, False),
        (SessionStatus.PAUSED, ["resume", "stop"], True, True, False),
        (SessionStatus.COMPLETED, [], False, True, True),
        (SessionStatus.FAILED, [], False, False, False),
    ],
)
def test_dashboard_capabilities_match_authoritative_session_state(
    session,
    status,
    actions,
    can_mutate,
    can_annotate,
    can_view_debrief,
):
    session.status = status
    session.save(update_fields=["status"])
    view_model = build_trainer_rest_view_model(load_trainer_engine_aggregate(session=session))
    capabilities = view_model.presentation.capabilities

    assert capabilities.lifecycle_actions == actions
    assert capabilities.can_record_learner_action is can_mutate
    assert capabilities.can_inject_event is can_mutate
    assert capabilities.can_override_patient_state is can_mutate
    assert capabilities.can_steer is can_mutate
    assert capabilities.can_annotate is can_annotate
    assert capabilities.can_view_debrief is can_view_debrief
    assert capabilities.can_tick_ai is (status == SessionStatus.RUNNING)
    assert capabilities.can_tick_vitals is (status == SessionStatus.RUNNING)


def test_public_state_schema_keeps_clock_and_dashboard_projection(session):
    view_model = build_trainer_rest_view_model(load_trainer_engine_aggregate(session=session))

    public = TrainerRestViewModelOut.model_validate(view_model.model_dump(mode="json"))
    payload = public.model_dump(mode="json")

    assert payload["runtime_snapshot"]["clock_observed_at"] is not None
    assert payload["presentation"]["primary_cue"] == "Watch for worsening respiratory effort."
    assert payload["presentation"]["capabilities"]["can_tick_ai"] is True
