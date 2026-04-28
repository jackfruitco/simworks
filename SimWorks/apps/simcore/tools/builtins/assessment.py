# simcore/tools/builtins/assessment.py
"""Tool that surfaces the latest initial-feedback Assessment for a simulation.

Replaces the legacy ``SimulationFeedbackTool``. The slug is now
``simulation_assessment`` and the data is the assessment-shaped payload
defined in :func:`apps.simcore.tools.serializers.serialize_assessment`.
"""

from apps.simcore.tools import GenericTool, register_tool
from apps.simcore.tools.serializers import serialize_assessment


@register_tool
class SimulationAssessmentTool(GenericTool):
    tool_name = "simulation_assessment"

    def get_data(self):
        from apps.assessments.models import Assessment, AssessmentSource

        assessment = (
            Assessment.objects.filter(
                sources__simulation=self.simulation,
                sources__source_type=AssessmentSource.SourceType.SIMULATION,
                sources__role=AssessmentSource.Role.PRIMARY,
                assessment_type="initial_feedback",
            )
            .select_related("rubric")
            .order_by("-created_at")
            .first()
        )
        if assessment is None:
            return []
        return [serialize_assessment(assessment)]
