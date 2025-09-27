"""Module to register custom LLM tools for function calling"""
from typing import Literal

from simcore.ai.schemas import NormalizedCustomTool


class CustomImageResponseTool(NormalizedCustomTool):
    type: Literal["get_patient_image_response"] = "get_patient_image_response"
    description = "Generate an image response as the patient based on the request from the provider"

    def name(self) -> str:
        return self.label
