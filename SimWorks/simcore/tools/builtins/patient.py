# simcore/tools/patient.py

from simcore.tools import BaseTool
from simcore.tools import register_tool

@register_tool
class PatientHistoryTool(BaseTool):
    tool_name = "patient_history"
    display_name = "Patient History"

    def get_data(self) -> list:
        from simcore.models import PatientHistory
        return [
            history.to_dict()
            for history in self.simulation.metadata.instance_of(PatientHistory)
        ]

    def to_dict(self):
        data = self.get_data()
        return self.default_dict(data=data)