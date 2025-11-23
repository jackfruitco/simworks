# simcore/tools/feedback.py
from simulation.tools import GenericTool, register_tool


@register_tool
class SimulationFeedbackTool(GenericTool):
    tool_name = "simulation_feedback"

    def get_data(self):
        from simulation.models import SimulationFeedback

        return self.simulation.metadata.instance_of(SimulationFeedback)

    def to_dict(self):
        data = self.get_data()
        return self.default_dict(data=data)
