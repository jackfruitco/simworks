# simcore/tools/simulation_metadata_tool.py

from simcore.tools import GenericTool
from simcore.tools import register_tool

@register_tool
class SimulationMetadataTool(GenericTool):
    tool_name = "simulation_metadata"

    def get_data(self):
        return self.simulation.metadata.exclude(attribute="feedback").exclude(attribute="patient history")