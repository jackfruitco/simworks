from django.db.models import Q

from apps.accounts.services import get_personal_account_for_user
from apps.assessments.models import Assessment
from apps.chatlab.models import Message
from apps.simcore.models import Simulation, SimulationSummary


def _typed_score_value(score):
    """Surface the typed value of an AssessmentCriterionScore for export."""
    vt = score.criterion.value_type
    if vt == "bool":
        return score.value_bool
    if vt == "int":
        return score.value_int
    if vt == "decimal":
        return float(score.value_decimal) if score.value_decimal is not None else None
    if vt in {"text", "enum"}:
        return score.value_text or None
    if vt == "json":
        return score.value_json
    return None


def build_user_export_payload(user) -> dict:
    personal_account = get_personal_account_for_user(user)
    simulation_filter = Q(account=personal_account) | Q(account__isnull=True, user=user)
    related_filter = Q(simulation__account=personal_account) | Q(
        simulation__account__isnull=True,
        simulation__user=user,
    )

    sims = Simulation.objects.filter(simulation_filter).order_by("id")
    messages = Message.objects.filter(related_filter).order_by("id")
    summaries = SimulationSummary.objects.filter(related_filter).order_by("id")
    assessments = (
        Assessment.objects.filter(assessed_user=user)
        .select_related("rubric")
        .prefetch_related("criterion_scores__criterion", "sources")
        .order_by("created_at")
    )

    return {
        "account": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": getattr(user.role, "title", None),
            "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        },
        "labs": [
            {
                "lab": m.lab.slug,
                "access_level": m.access_level,
                "is_active": m.is_active,
            }
            for m in user.lab_memberships.select_related("lab").all()
        ],
        "simulations": [
            {
                "id": sim.id,
                "status": sim.status,
                "start_timestamp": sim.start_timestamp.isoformat() if sim.start_timestamp else None,
                "end_timestamp": sim.end_timestamp.isoformat() if sim.end_timestamp else None,
                "diagnosis": sim.diagnosis,
                "chief_complaint": sim.chief_complaint,
            }
            for sim in sims
        ],
        "messages": [
            {
                "id": message.id,
                "simulation_id": message.simulation_id,
                "conversation_id": message.conversation_id,
                "timestamp": message.timestamp.isoformat() if message.timestamp else None,
                "role": message.role,
                "content": message.content,
                "message_type": message.message_type,
            }
            for message in messages
        ],
        "simulation_summaries": [
            {
                "simulation_id": summary.simulation_id,
                "summary_text": summary.summary_text,
                "chief_complaint": summary.chief_complaint,
                "diagnosis": summary.diagnosis,
                "strengths": summary.strengths,
                "improvement_areas": summary.improvement_areas,
                "learning_points": summary.learning_points,
                "recommended_study_topics": summary.recommended_study_topics,
            }
            for summary in summaries
        ],
        "assessments": [
            {
                "id": str(assessment.id),
                "assessment_type": assessment.assessment_type,
                "lab_type": assessment.lab_type,
                "rubric": {
                    "slug": assessment.rubric.slug,
                    "version": assessment.rubric.version,
                    "name": assessment.rubric.name,
                },
                "overall_summary": assessment.overall_summary,
                "overall_score": (
                    float(assessment.overall_score)
                    if assessment.overall_score is not None
                    else None
                ),
                "created_at": assessment.created_at.isoformat(),
                "criterion_scores": [
                    {
                        "criterion_slug": cs.criterion.slug,
                        "value": _typed_score_value(cs),
                        "score": float(cs.score) if cs.score is not None else None,
                        "rationale": cs.rationale,
                    }
                    for cs in assessment.criterion_scores.all()
                ],
                "sources": [
                    {
                        "source_type": src.source_type,
                        "role": src.role,
                        "simulation_id": src.simulation_id,
                        "source_assessment_id": (
                            str(src.source_assessment_id) if src.source_assessment_id else None
                        ),
                    }
                    for src in assessment.sources.all()
                ],
            }
            for assessment in assessments
        ],
    }
