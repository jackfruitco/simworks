# simcore/tools/patient.py
import logging

from simulation.tools import BaseTool, register_tool
logger = logging.getLogger(__name__)


@register_tool
class PatientHistoryTool(BaseTool):
    tool_name = "patient_history"
    display_name = "Patient History"

    def get_data(self) -> list:
        from simulation.models import PatientHistory

        return [
            history.to_dict()
            for history in self.simulation.metadata.instance_of(PatientHistory)
        ]

    def to_dict(self):
        data = self.get_data()
        return self.default_dict(data=data)


@register_tool
class PatientResultsTool(BaseTool):
    tool_name = "patient_results"
    display_name = "Patient Results"
    is_generic = False

    def new_order(self, order):
        pass

    def get_data(self) -> list:
        from simulation.models import LabResult

        return [
            result.serialize()
            for result in self.simulation.metadata.instance_of(LabResult)
        ]

    def to_dict(self):
        data = self.get_data()
        return self.default_dict(data=data)
