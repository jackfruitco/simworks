# simcore/tools/feedback.py
from apps.simcore.tools import GenericTool, register_tool
from apps.simcore.tools.serializers import serialize_simulation_feedback


@register_tool
class SimulationFeedbackTool(GenericTool):
    tool_name = "simulation_feedback"

    def get_data(self):
        from apps.simcore.models import SimulationFeedback

        return [
            serialize_simulation_feedback(item)
            for item in self.simulation.metadata.instance_of(SimulationFeedback).order_by("pk")
        ]
