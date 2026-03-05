# simcore/tools/metadata.py
from apps.simcore.tools import GenericTool, register_tool


@register_tool
class SimulationMetadataTool(GenericTool):
    tool_name = "simulation_metadata"

    def get_data(self):
        from apps.simcore.models import PatientDemographics

        return self.simulation.metadata.instance_of(PatientDemographics)

    def to_dict(self):
        data = self.get_data()
        return self.default_dict(data=data)
