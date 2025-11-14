# chatlab/ai/codecs/patient.py
from chatlab.ai.mixins import ChatlabMixin
from config.ai.codecs import SimWorksCodec
from chatlab.models import Message, RoleChoices
from simcore.ai.mixins import StandardizedPatientMixin
from simcore.models import SimulationMetadata, PatientHistory, PatientDemographics, LabResult, RadResult
from simcore_ai_django.api import simcore

@simcore.codec
class PatientInitialResponseCodec(ChatlabMixin, StandardizedPatientMixin, SimWorksCodec):
    schema_model_map = {
        "messages": Message,
        "metadata": {
            "patient_history": PatientHistory,
            "patient_demographics": PatientDemographics,
            "default": SimulationMetadata,
        },
    }
    section_defaults = {
        "messages": lambda ctx: {
            "simulation": ctx["simulation"],
            "sender": ctx.get("sender") or ctx["simulation"].user,
            "role": RoleChoices.ASSISTANT,
            "is_from_ai": True,
        },
        "metadata": lambda ctx: {"simulation": ctx["simulation"]},
    }
    section_kind_field = "kind"

@simcore.codec
class PatientReplyCodec(ChatlabMixin, StandardizedPatientMixin, SimWorksCodec):
    schema_model_map = {"messages": Message}
    section_defaults = {
        "messages": lambda ctx: {
            "simulation": ctx["simulation"],
            "sender": ctx.get("sender") or ctx["simulation"].user,
            "role": RoleChoices.ASSISTANT,
            "is_from_ai": True,
        }
    }

@simcore.codec
class PatientResultsCodec(ChatlabMixin, StandardizedPatientMixin, SimWorksCodec):
    schema_model_map = {
        "metadata": {
            "lab_result": LabResult,
            "rad_result": RadResult,
            "default": SimulationMetadata,
        },
    }
    section_defaults = {"metadata": lambda ctx: {"simulation": ctx["simulation"]}}
    section_kind_field = "kind"
    create_assistant_message = False  # results don’t post a chat bubble