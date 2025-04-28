# simcore/tools/patient_metadata_tool.py

from simcore.tools import BaseTool
from simcore.tools import register_tool

@register_tool
class PatientMetadataTool(BaseTool):
    tool_name = "patient_metadata"
    display_name = "Patient History"

    def get_data(self):
        return self.simulation.formatted_patient_history

    def to_dict(self):
        data = self.get_data()
        return self.default_dict(data=data)