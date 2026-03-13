# simcore/tools/patient.py
import logging

from apps.simcore.tools import BaseTool, register_tool
from apps.simcore.tools.serializers import serialize_lab_result, serialize_patient_history

logger = logging.getLogger(__name__)


@register_tool
class PatientHistoryTool(BaseTool):
    tool_name = "patient_history"
    display_name = "Patient History"

    def get_data(self) -> list:
        from apps.simcore.models import PatientHistory

        return [
            serialize_patient_history(history)
            for history in self.simulation.metadata.instance_of(PatientHistory).order_by("pk")
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
        from apps.simcore.models import LabResult

        return [
            serialize_lab_result(result)
            for result in self.simulation.metadata.instance_of(LabResult).order_by("pk")
        ]

    def to_dict(self):
        data = self.get_data()
        return self.default_dict(data=data)
