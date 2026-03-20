from apps.chatlab.models import Message
from apps.simcore.models import Simulation, SimulationFeedback, SimulationSummary


def build_user_export_payload(user) -> dict:
    sims = Simulation.objects.filter(user=user).order_by("id")
    messages = Message.objects.filter(simulation__user=user).order_by("id")
    summaries = SimulationSummary.objects.filter(simulation__user=user).order_by("id")
    feedback = SimulationFeedback.objects.filter(simulation__user=user).order_by("id")

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
        "simulation_feedback": [
            {
                "simulation_id": item.simulation_id,
                "key": item.key,
                "value": item.value,
            }
            for item in feedback
        ],
    }
