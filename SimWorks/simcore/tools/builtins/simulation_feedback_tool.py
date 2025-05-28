# simcore/tools/simulation_feedback_tool.py

from simcore.tools import GenericTool
from simcore.tools import register_tool

@register_tool
class SimulationFeedbackTool(GenericTool):
    tool_name = "simulation_feedback"

    def get_data(self):
        from simcore.models import SimulationFeedback
        return self.simulation.metadata.instance_of(SimulationFeedback)

    def to_dict(self):
        data = self.get_data()
        return self.default_dict(data=data)