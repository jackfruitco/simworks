# simcore/tools/metadata.py
from apps.simcore.tools import GenericTool, register_tool
from apps.simcore.tools.serializers import serialize_patient_demographics


@register_tool
class SimulationMetadataTool(GenericTool):
    tool_name = "simulation_metadata"

    def get_data(self):
        from apps.simcore.models import PatientDemographics

        return [
            serialize_patient_demographics(item)
            for item in self.simulation.metadata.instance_of(PatientDemographics).order_by("pk")
        ]
