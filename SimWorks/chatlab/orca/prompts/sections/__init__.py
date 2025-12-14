# chatlab/ai/prompts/sections/__init__.py
from .patient_responses import *
from .base import *

__all__ = [
    "ChatlabBaseSection",
    "ChatlabPatientInitialSection",
    "ChatlabPatientReplySection",
    "ChatlabImageSection",
]