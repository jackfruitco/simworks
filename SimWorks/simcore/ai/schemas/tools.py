from typing import Literal, Optional

from django.conf import settings
from pydantic import Field

from . import StrictBaseModel
from .normalized_types import NormalizedAITool


class NormalizedToolParameter(StrictBaseModel):
    type: str
    properties: dict


class NormalizedCustomTool(NormalizedAITool):
    type: Literal["function"] = "function"
    description: Optional[str]
    parameters: list[NormalizedToolParameter] = Field(default_factory=list)
    strict: Optional[bool] = True


class NormalizedImageGenerationTool(NormalizedAITool):
    type: Literal["image_generation"] = "image_generation"

    model: str = settings.AI_IMAGE_MODEL

    output_compression: Optional[str] = settings.AI_IMAGE_OUTPUT_COMPRESSION
    output_format: str = settings.AI_IMAGE_FORMAT
    quality: Literal["low", "medium", "high", "auto"] = settings.AI_IMAGE_QUALITY
    size: Literal["1024x1024", "1024x1536", "1536x1024", "auto"] = settings.AI_IMAGE_SIZE
    background: Literal["transparent", "opaque", "auto"] = settings.AI_IMAGE_BACKGROUND
    moderation: Literal["auto", "low"] = settings.AI_IMAGE_MODERATION
