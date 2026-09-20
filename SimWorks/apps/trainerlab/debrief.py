"""Evidence projection and generation ownership for instructor-facing debriefs."""

from datetime import timedelta
import hashlib
import json
from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import SessionStatus, TrainerRunSummary, TrainerSession


def project_evidence(session, events):
    """Exclude commands, recommendations, raw transcripts and AI reasoning."""
    evidence = []
    fact_keys = {
        "domain_event_id",
        "domain_event_type",
        "source",
        "supersedes_event_id",
        "intervention_type",
        "intervention_label",
        "site_code",
        "site_label",
        "target_problem_id",
        "status",
        "effectiveness",
        "details",
        "details_json",
        "title",
        "kind",
        "severity",
        "description",
        "injury_location",
        "injury_kind",
        "injury_description",
        "name",
        "vital_type",
        "min_value",
        "max_value",
        "min_value_diastolic",
        "max_value_diastolic",
        "value",
        "location",
        "finding",
        "anatomical_location",
        "active",
        "action",
        "from",
        "to",
        "elapsed_seconds",
    }
    for event in events:
        kind = event.event_type
        if (
            not (kind.startswith("patient.") or kind == "simulation.status.updated")
            or "recommend" in kind
        ):
            continue
        payload = event.payload or {}
        is_action = kind == "patient.intervention.created"
        if is_action and payload.get("source") not in {"instructor", "user", "system"}:
            continue
        evidence.append(
            {
                "id": f"event:{event.id}",
                "kind": "learner_action" if is_action else "patient_change",
                "event_type": kind,
                "event_sequence": event.sequence,
                "created_at": event.created_at.isoformat(),
                "facts": {key: value for key, value in payload.items() if key in fact_keys},
            }
        )
    for annotation in session.debrief_annotations.order_by("created_at", "id"):
        evidence.append(
            {
                "id": f"annotation:{annotation.pk}",
                "kind": "instructor_observation",
                "event_type": "instructor.observation",
                "created_at": annotation.created_at.isoformat(),
                "facts": {
                    "observation": annotation.observation_text,
                    "outcome": annotation.outcome,
                    "learning_objective": annotation.learning_objective,
                    "linked_domain_event_id": annotation.linked_event_id,
                    "elapsed_seconds": annotation.elapsed_seconds_at,
                    "created_by_id": annotation.created_by_id,
                },
            }
        )
    # Keep all authoritative actions/observations; bound repetitive physiology with explicit coverage.
    changes = [item for item in evidence if item["kind"] == "patient_change"]
    keep = {item["id"] for item in changes[:20] + changes[-280:]}
    filtered = [item for item in evidence if item["kind"] != "patient_change" or item["id"] in keep]
    revision = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return filtered, revision, len(evidence) - len(filtered)


def _notify(session, summary, correlation_id=None):
    from .services import emit_runtime_event

    data = summary.summary_json
    emit_runtime_event(
        session=session,
        event_type="simulation.summary.updated",
        payload={
            "summary_id": summary.pk,
            "status": data["debrief_status"],
            "evidence_revision": data.get("evidence_revision"),
            "ai_debrief_revision": data.get("ai_debrief_revision", 0),
        },
        correlation_id=correlation_id,
    )


def _save(summary, data):
    summary.summary_json = data
    summary.generator_version = "v3"
    summary.save(update_fields=["summary_json", "generator_version"])


def _expired(data):
    started = parse_datetime(data.get("debrief_requested_at") or "")
    return started is None or timezone.now() - started > timedelta(minutes=5)


def _owns(data, context):
    return (
        data.get("debrief_status") == "generating"
        and context.get("debrief_generation") == data.get("debrief_generation")
        and context.get("evidence_revision") == data.get("evidence_revision")
    )


@transaction.atomic
def request_debrief(*, session, correlation_id=None):
    session = TrainerSession.objects.select_for_update().get(pk=session.pk)
    summary = TrainerRunSummary.objects.get(session=session)
    data = dict(summary.summary_json)
    if session.status != SessionStatus.COMPLETED:
        return None
    if data.get("debrief_status") == "generating" and not _expired(data):
        return data.get("debrief_generation")
    generation = str(uuid4())
    data.update(
        debrief_status="generating",
        debrief_generation=generation,
        debrief_requested_at=timezone.now().isoformat(),
        debrief_error=None,
    )
    _save(summary, data)
    _notify(session, summary, correlation_id)
    context = {
        "simulation_id": session.simulation_id,
        "session_id": session.pk,
        "debrief_generation": generation,
        "evidence_revision": data["evidence_revision"],
        "evidence": data["evidence"],
        "evidence_omitted_count": data.get("evidence_omitted_count", 0),
        "correlation_id": correlation_id,
    }

    def enqueue():
        from .orca.services import GenerateTrainerRunDebrief

        try:
            GenerateTrainerRunDebrief.task.using(context=context).enqueue(
                user_message="Generate an evidence-linked instructor debrief.",
            )
        except Exception:
            fail_debrief(session_id=session.pk, context=context, error="enqueue_failed")

    transaction.on_commit(enqueue)
    return generation


@transaction.atomic
def fail_debrief(*, session_id, context, error="generation_failed"):
    session = TrainerSession.objects.select_for_update().get(pk=session_id)
    summary = TrainerRunSummary.objects.get(session=session)
    data = dict(summary.summary_json)
    if not _owns(data, context):
        return
    data.update(debrief_status="failed", debrief_error=error)
    _save(summary, data)
    _notify(session, summary, context.get("correlation_id"))


@transaction.atomic
def summary_for_review(session):
    session = TrainerSession.objects.select_for_update().get(pk=session.pk)
    summary = TrainerRunSummary.objects.filter(session=session).first()
    if summary and "evidence_revision" not in summary.summary_json:
        from .services import build_summary

        summary = build_summary(session=session)
    if (
        summary
        and summary.summary_json.get("debrief_status") == "generating"
        and _expired(summary.summary_json)
    ):
        data = dict(summary.summary_json)
        data.update(debrief_status="failed", debrief_error="generation_timed_out")
        _save(summary, data)
        _notify(session, summary)
    return summary


@transaction.atomic
def apply_output(*, session_id, output_payload, context):
    from .orca.schemas.debrief import TrainerRunDebriefOutput

    session = TrainerSession.objects.select_for_update().get(pk=session_id)
    summary = TrainerRunSummary.objects.get(session=session)
    data = dict(summary.summary_json)
    if session.status != SessionStatus.COMPLETED or not _owns(data, context):
        return summary
    if _expired(data):
        fail_debrief(session_id=session_id, context=context, error="generation_timed_out")
        return TrainerRunSummary.objects.get(pk=summary.pk)
    try:
        parsed = TrainerRunDebriefOutput.model_validate(output_payload)
        evidence = {item["id"]: item for item in data["evidence"]}
        claims = []
        for index, claim in enumerate(parsed.claims):
            if not set(claim.evidence_ids).issubset(evidence):
                raise ValueError("Unknown evidence reference")
            if claim.category == "strength" and not any(
                evidence[key]["kind"] == "learner_action"
                or (
                    evidence[key]["kind"] == "instructor_observation"
                    and evidence[key]["facts"].get("outcome") in {"correct", "improvised"}
                )
                for key in claim.evidence_ids
            ):
                raise ValueError(
                    "Learner credit requires action or instructor observation evidence"
                )
            if claim.category == "miss" and not any(
                evidence[key]["kind"] == "instructor_observation"
                and evidence[key]["facts"].get("outcome") in {"missed", "incorrect"}
                for key in claim.evidence_ids
            ):
                raise ValueError("Absence of a record is not proof of a missed action")
            claims.append({"id": f"{data['debrief_generation']}:{index}", **claim.model_dump()})
    except (ValueError, TypeError):
        fail_debrief(session_id=session_id, context=context, error="invalid_evidence")
        return TrainerRunSummary.objects.get(pk=summary.pk)

    def texts(category):
        return [claim["text"] for claim in claims if claim["category"] == category]

    output = {
        "claims": claims,
        "narrative_summary": "\n".join(texts("summary")),
        "strengths": texts("strength"),
        "misses": texts("miss"),
        "teaching_points": texts("teaching_point"),
        "overall_assessment": "\n".join(texts("assessment")),
        "deterioration_timeline": [],
    }
    data.update(
        ai_debrief=output,
        ai_debrief_revision=int(data.get("ai_debrief_revision", 0)) + 1,
        debrief_status="ready",
        debrief_error=None,
        debrief_completed_at=timezone.now().isoformat(),
        debrief_evidence_revision=data["evidence_revision"],
    )
    _save(summary, data)
    _notify(session, summary, context.get("correlation_id"))
    return summary
