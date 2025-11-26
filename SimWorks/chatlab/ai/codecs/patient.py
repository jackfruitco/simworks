# chatlab/ai/codecs/patient.py
"""
This module provides codec classes for handling patient-related simulation data
including initial responses, replies, and result metadata. The module is deprecated
and no longer aligns with supported codec practices.

Classes in this module provide mechanisms for mapping and transforming patient-specific
data within simulations, integrating specialized mixins, and supporting context-based
defaults for schema modeling.

.. warning::
    This module is deprecated. Service-based codecs are no longer supported.
    Codecs should align with providers' result types.

"""
import warnings
# from chatlab.models import Message, RoleChoices
# from config.ai.codecs import SimWorksCodec
# from simcore_ai_django.api import simcore
# from simulation.ai.mixins import StandardizedPatientMixin
# from simulation.models import SimulationMetadata, PatientHistory, PatientDemographics, LabResult, RadResult
# from ..mixins import ChatlabMixin
#
#

warnings.warn("this module is deprecated. Service-based codecs are no longer support. Codecs should align with providers result type.")
# @simcore.codec
# class PatientInitialResponseCodec(ChatlabMixin, StandardizedPatientMixin, SimWorksCodec):
#     schema_model_map = {
#         "input": Message,
#         "metadata": {
#             "patient_history": PatientHistory,
#             "patient_demographics": PatientDemographics,
#             "default": SimulationMetadata,
#         },
#     }
#     section_defaults = {
#         "input": lambda ctx: {
#             "simulation": ctx["simulation"],
#             "sender": ctx.get("sender") or ctx["simulation"].user,
#             "role": RoleChoices.ASSISTANT,
#             "is_from_ai": True,
#         },
#         "metadata": lambda ctx: {"simulation": ctx["simulation"]},
#     }
#     section_kind_field = "kind"
#
#
# @simcore.codec
# class PatientReplyCodec(ChatlabMixin, StandardizedPatientMixin, SimWorksCodec):
#     schema_model_map = {"input": Message}
#     section_defaults = {
#         "input": lambda ctx: {
#             "simulation": ctx["simulation"],
#             "sender": ctx.get("sender") or ctx["simulation"].user,
#             "role": RoleChoices.ASSISTANT,
#             "is_from_ai": True,
#         }
#     }
#
#
# @simcore.codec
# class PatientResultsCodec(ChatlabMixin, StandardizedPatientMixin, SimWorksCodec):
#     schema_model_map = {
#         "metadata": {
#             "lab_result": LabResult,
#             "rad_result": RadResult,
#             "default": SimulationMetadata,
#         },
#     }
#     section_defaults = {"metadata": lambda ctx: {"simulation": ctx["simulation"]}}
#     section_kind_field = "kind"
#     create_assistant_message = False  # results don’t post a chat bubble
