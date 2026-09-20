from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
import pytest

from apps.accounts.models import UserRole
from apps.trainerlab.debrief import apply_output, fail_debrief, request_debrief, summary_for_review
from apps.trainerlab.models import DebriefAnnotation, RuntimeEvent, TrainerRunSummary
from apps.trainerlab.services import (
    build_summary,
    create_debrief_annotation,
    create_session,
    emit_runtime_event,
    stop_session,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="debrief@example.com",
        password="test",
        role=UserRole.objects.create(title="Debrief instructor"),
    )
    session = create_session(user=user, scenario_spec={}, directives="", modifiers=[])
    session.status = "running"
    session.save(update_fields=["status"])
    emit_runtime_event(
        session=session,
        event_type="patient.intervention.created",
        payload={
            "source": "instructor",
            "intervention_type": "tourniquet",
            "site_code": "LEFT_ARM",
            "domain_event_id": 123,
            "status": "applied",
        },
    )
    return stop_session(session=session, user=user)


def data(session):
    return TrainerRunSummary.objects.get(session=session).summary_json


def context(session):
    return {key: data(session)[key] for key in ("debrief_generation", "evidence_revision")}


def output(session, category="strength", evidence_ids=None):
    action = next(item for item in data(session)["evidence"] if item["kind"] == "learner_action")
    return {
        "claims": [
            {
                "category": category,
                "text": "Tourniquet application was recorded.",
                "evidence_ids": evidence_ids or [action["id"]],
            }
        ]
    }


def test_stop_evidence_is_immediate_and_callback_is_idempotent(session):
    assert data(session)["debrief_status"] == "generating"
    ctx = context(session)
    apply_output(session_id=session.pk, output_payload=output(session), context=ctx)
    apply_output(session_id=session.pk, output_payload=output(session), context=ctx)
    assert data(session)["debrief_status"] == "ready"
    assert data(session)["ai_debrief_revision"] == 1


@pytest.mark.parametrize("category,refs", [("summary", ["event:invented"]), ("miss", None)])
def test_invalid_references_and_unobserved_misses_fail_closed(session, category, refs):
    apply_output(
        session_id=session.pk,
        output_payload=output(session, category, refs),
        context=context(session),
    )
    assert data(session)["debrief_status"] == "failed"
    assert data(session)["debrief_error"] == "invalid_evidence"
    assert data(session)["ai_debrief"] is None


def test_annotation_invalidates_old_generation_and_failure(session):
    old = context(session)
    create_debrief_annotation(
        session=session,
        created_by=None,
        learning_objective="other",
        observation_text="Instructor observed delayed reassessment.",
        outcome="missed",
    )
    assert context(session) != old
    apply_output(session_id=session.pk, output_payload=output(session), context=old)
    fail_debrief(session_id=session.pk, context=old)
    assert data(session)["debrief_status"] == "generating"
    annotation = DebriefAnnotation.objects.get(session=session)
    apply_output(
        session_id=session.pk,
        context=context(session),
        output_payload=output(session, "miss", [f"annotation:{annotation.pk}"]),
    )
    assert data(session)["debrief_status"] == "ready"


def test_timeout_retry_rejects_late_success(session):
    old = context(session)
    summary = TrainerRunSummary.objects.get(session=session)
    summary.summary_json["debrief_requested_at"] = (
        timezone.now() - timedelta(minutes=6)
    ).isoformat()
    summary.save()
    assert summary_for_review(session).summary_json["debrief_error"] == "generation_timed_out"
    request_debrief(session=session)
    new = context(session)
    assert new != old
    apply_output(session_id=session.pk, output_payload=output(session), context=old)
    assert data(session)["ai_debrief"] is None
    apply_output(session_id=session.pk, output_payload=output(session), context=new)
    assert data(session)["debrief_status"] == "ready"


def test_projection_excludes_transcripts_recommendations_and_ai_actions(session):
    for event_type, payload in [
        (
            "simulation.command.accepted",
            {"voice_provenance": {"original_transcript": "SECRET DRAFT"}},
        ),
        ("patient.intervention.created", {"source": "ai", "intervention_type": "invented"}),
        ("patient.recommendation.created", {"description": "Suggested care"}),
    ]:
        RuntimeEvent.objects.create(
            session=session, simulation=session.simulation, event_type=event_type, payload=payload
        )
    summary = build_summary(session=session)
    evidence = str(summary.summary_json["evidence"])
    assert "SECRET DRAFT" not in evidence
    assert "invented" not in evidence
    assert "Suggested care" not in evidence
    assert "tourniquet" in evidence


def test_enqueue_failure_is_visible_and_not_a_hanging_spinner(
    session, django_capture_on_commit_callbacks
):
    fail_debrief(session_id=session.pk, context=context(session))
    with patch("apps.trainerlab.orca.services.GenerateTrainerRunDebrief.task") as task:
        task.using.side_effect = RuntimeError("broker unavailable")
        with django_capture_on_commit_callbacks(execute=True):
            request_debrief(session=session)
    assert data(session)["debrief_error"] == "enqueue_failed"


def test_duplicate_generation_requests_coalesce(session):
    generation = request_debrief(session=session)
    assert request_debrief(session=session) == generation
