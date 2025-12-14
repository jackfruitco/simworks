"""Module to register custom LLM tools for function calling"""
from typing import Literal

from orchestrai_django.types import DjangoLLMBaseTool

class CustomImageResponseTool(DjangoLLMBaseTool):
    type: Literal["get_patient_image_response"] = "get_patient_image_response"
    description = "Generate an image response as the patient based on the request from the backend"

    def name(self) -> str:
        return self.label
