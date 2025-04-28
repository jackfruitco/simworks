# simcore/tools/simulation_feedback_tool.py

from simcore.tools import GenericTool
from simcore.tools import register_tool

@register_tool
class SimulationFeedbackTool(GenericTool):
    tool_name = "simulation_feedback"

    def get_data(self):
        return self.simulation.metadata.filter(attribute="feedback")
