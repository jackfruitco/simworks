# simcore_ai/types/transport.py
"""
Defines data transfer objects (DTOs) for requests, responses, and stream chunks used
in the system.

The module provides models for handling the structure and validation of data related
to requests, responses, and streaming operations. These models serve as the interface
between different components, ensuring consistent data flow and type safety.

Classes:
    - Request: Represents the structure of a request object containing parameters,
      metadata, and tooling information.
    - Response: Encapsulates the structure of a response object including identity,
      timing information, output, and usage statistics.
    - StreamChunk: Represents a chunk of stream data for incremental processing.

"""
import logging
from datetime import datetime
from typing import Any, Dict, TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .base import StrictBaseModel
from .messages import InputItem, OutputItem, UsageContent
from .tools import BaseLLMTool, LLMToolChoice, LLMToolCall, LLMToolCallDelta

logger = logging.getLogger(__name__)

ResponseSchemaType: TypeAlias = type[BaseModel]  # TODO: ResponseSchemaType Protocol


# ---------- Request/Response (DTO) -------------------------------------------------
class Request(StrictBaseModel):
    model: str | None = None
    input: list[InputItem]

    # Identity
    namespace: str | None = None
    kind: str | None = None
    name: str | None = None

    # Correlation
    correlation_id: UUID = Field(default_factory=uuid4)

    # Response format (provider-agnostic)
    response_schema: ResponseSchemaType | None = None  # Pydantic model
    response_schema_json: dict | None = None  # JSON schema from the model
    provider_response_format: dict | None = None  # Provider-specific response format

    # Tooling
    tools: list[BaseLLMTool] = Field(default_factory=list)
    tool_choice: LLMToolChoice = "auto"

    # Misc
    previous_response_id: str | None = None
    temperature: float | None = 0.2
    max_output_tokens: int | None = None
    stream: bool = False
    image_format: str | None = None


class Response(StrictBaseModel):
    # Identity echoed back (operation identity)
    namespace: str | None = None
    kind: str | None = None
    name: str | None = None

    # Correlation
    correlation_id: UUID = Field(default_factory=uuid4)

    # Request
    request_correlation_id: UUID | None = None
    request: Request | None = None

    # Provider/client + timing
    provider_name: str | None = None
    client_name: str | None = None
    received_at: datetime | None = None

    output: list[OutputItem] = Field(default_factory=list)
    usage: UsageContent | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    provider_meta: dict[str, Any] = Field(default_factory=dict)


class StreamChunk(StrictBaseModel):
    correlation_id: UUID = Field(default_factory=uuid4)
    lab_key: str
    simulation_id: int

    is_final: bool = False
    delta: str = ""
    tool_call_delta: LLMToolCallDelta | None = None
    usage_partial: Dict[str, int] | None = None
