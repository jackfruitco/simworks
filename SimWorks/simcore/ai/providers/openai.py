# simcore/ai/providers/openai.py
from __future__ import annotations

import logging
from typing import Any

from openai import (
    AsyncOpenAI,
    NotGiven,
    NOT_GIVEN
)
from openai.types.responses import (
    Response as OpenAIResponse,
    ResponseTextConfigParam,
    ResponseUsage as OpenAIUsage,
)
from openai.types.responses.response_output_item import ImageGenerationCall
from openai.types.responses.tool import ImageGeneration
from pydantic import TypeAdapter

from .base import ProviderBase, ToolAdapter
from ..parsers.output_parser import maybe_parse_to_schema
from ..schemas.normalized_types import (
    NormalizedAIMessage,
    NormalizedAIMetadata,
    NormalizedAIRequest,
    NormalizedAIResponse,
    NormalizedStreamChunk, NormalizedAITool, NormalizedAttachment
)
from ..schemas.tools import NormalizedImageGenerationTool
from ..utils.helpers import build_output_schema

logger = logging.getLogger(__name__)


class OpenAIImageToolAdapter(ToolAdapter):
    """Adapter for OpenAI Image Generation Tool

    Includes: `to_provider` and `from_provider` methods
    """
    provider = "openai"

    def to_provider(self, tool: NormalizedImageGenerationTool) -> Any:
        """Adapt NormalizedAITool to OpenAI ImageGenerationTool"""

        # Pop keys not supported by OpenAI API
        kwargs = tool.model_dump(exclude_none=True)
        allowed = getattr(ImageGeneration, "model_fields", {}).keys()
        filtered = {k: v for k, v in kwargs.items() if k in allowed}

        return ImageGeneration(**filtered)

    def from_provider(self, raw: ImageGeneration) -> NormalizedImageGenerationTool:
        """Adapt OpenAI ImageGenerationTool to NormalizedAITool"""
        return NormalizedImageGenerationTool(
            function="generate",
            arguments=raw.model_dump(),
        )


# Provider-local tool adapter registry
_ADAPTERS: dict[type[NormalizedAITool], ToolAdapter] = {
    NormalizedImageGenerationTool: OpenAIImageToolAdapter(),
}


def resolve_adapter_for(tool: NormalizedAITool) -> ToolAdapter:
    """Resolve provider tool adapter for a given normalized tool type"""
    for cls in type(tool).mro():
        if cls in _ADAPTERS:
            return _ADAPTERS[cls]
    raise NotImplementedError(f"{type(tool).__name__} not supported by {__name__}")


def _adapt_tools(tools: list[NormalizedAITool] | None) -> list[Any]:
    """Adapt a list of NormalizedAITools to provider-specific tool objects"""
    out: list[Any] = []
    for t in tools or []:
        adapter = resolve_adapter_for(t)
        out.append(adapter.to_provider(t))
    return out


def available_tools() -> list[NormalizedAITool]:
    """List available tools for OpenAI provider"""
    return [
        NormalizedImageGenerationTool(
            function="generate",
            arguments={},
        ),
    ]


def _coerce_usage(usage_obj) -> dict:
    """
    Coerce OpenAI ResponseUsage into the flat dict shape our NormalizedAIResponse expects.
    Falls back to None for any missing fields.
    """
    if not usage_obj:
        return {}
    # Plain attributes on the OpenAI SDK object, with safe fallbacks
    input_tokens = getattr(usage_obj, "input_tokens", None)
    output_tokens = getattr(usage_obj, "output_tokens", None)
    total_tokens = getattr(usage_obj, "total_tokens", None)
    itd = getattr(usage_obj, "input_tokens_details", None)
    otd = getattr(usage_obj, "output_tokens_details", None)
    input_tokens_details = getattr(itd, "cached_tokens", None) if itd is not None else None
    output_tokens_details = getattr(otd, "reasoning_tokens", None) if otd is not None else None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "input_tokens_details": input_tokens_details,
        "output_tokens_details": output_tokens_details,
    }


def _iter_metadata_items(md):
    """
    Yield flattened metadata dicts from the parsed schema's `metadata` object.
    Supports the PatientInitialOutputSchema shape:
      {
        "patient_demographics": [{key, value}],
        "patient_history": [{key, value|null, is_resolved, duration}],
        "simulation_metadata": [{key, value}],
        "scenario_data": {diagnosis, chief_complaint}
      }
    Produces generic meta rows with a `type` discriminator and optional `extra`.
    """
    if not md:
        return

    # Dump to dict if provided as a Pydantic model
    if hasattr(md, "model_dump"):
        md = md.model_dump()

    # If the provider already returned a list of union-shaped items, forward them
    if isinstance(md, list):
        for item in md:
            yield item
        return
    # Expect a dict with the structured sections
    if isinstance(md, dict):
        # patient_demographics
        for item in md.get("patient_demographics", []) or []:
            if isinstance(item, dict):
                yield {
                    "type": "patient_demographics",
                    "key": item.get("key", "meta"),
                    "value": item.get("value"),
                }
        # patient_history
        for item in md.get("patient_history", []) or []:
            if isinstance(item, dict):
                yield {
                    "type": "patient_history",
                    "key": item.get("key", "history"),
                    "value": item.get("value") or "None",
                    "is_resolved": item.get("is_resolved"),
                    "duration": item.get("duration"),
                }
        # simulation_metadata
        for item in md.get("simulation_metadata", []) or []:
            if isinstance(item, dict):
                yield {
                    "type": "simulation_metadata",
                    "key": item.get("key", "meta"),
                    "value": item.get("value"),
                }
        # scenario_data
        sd = md.get("scenario_data")
        if isinstance(sd, dict):
            if "diagnosis" in sd:
                yield {"type": "scenario", "key": "diagnosis", "value": sd.get("diagnosis")}
            if "chief_complaint" in sd:
                yield {"type": "scenario", "key": "chief_complaint", "value": sd.get("chief_complaint")}
        return
    # Fallback: unknown shape → nothing
    return


_META_ADAPTER = TypeAdapter(NormalizedAIMetadata)


# Normalize OpenAI Responses API objects to our schema -----------------------
def normalize_response(resp: OpenAIResponse, *, schema_cls=None) -> NormalizedAIResponse:
    """
    Parse OpenAI Responses API output using the standardized `output_text`.
    If a Pydantic schema class is provided (e.g., PatientInitialOutputSchema),
    attempt to coerce the text back into that schema; otherwise return the raw text.
    """
    # Get `output_text` from the OpenAI Responses API Response object
    # see https://platform.openai.com/docs/api-reference/responses/object#responses/object-output_text
    logger.debug(f"provider normalizing {resp.__class__.__name__} to {NormalizedAIResponse.__name__}")

    text: str = getattr(resp, "output_text", None)
    usage_obj: OpenAIUsage = getattr(resp, "usage", None)
    _usage = _coerce_usage(usage_obj)
    parsed_messages_present = False

    if text:
        if schema_cls is not None:
            _parsed = maybe_parse_to_schema(text, schema_cls)
        else:
            _parsed = None
        if not _parsed or isinstance(_parsed, str):
            logger.warning("Could not parse output_text to schema.")
        else:
            parsed_messages_present = bool(getattr(_parsed, "messages", None))
    else:
        _parsed = None

    if not text and not getattr(resp, "output", None):
        msg = "No output_text or output found on OpenAI response"
        raise ValueError(msg)

    _messages: list[NormalizedAIMessage] = []
    _metadata: list[NormalizedAIMetadata] = []
    _attachments: list[NormalizedAttachment] = []

    # Parse and normalize message(s)
    for raw_msg in (getattr(_parsed, "messages", None) or []):
        _messages.append(
            NormalizedAIMessage(role=raw_msg.role, content=raw_msg.content)
        )

    total, count = len(_messages), 1
    for m in _messages:
        logger.debug(f"... message ({count} of {total}) normalized: {m}")
        count += 1

    # Parse and normalize attachments (e.g. Images)
    for item in getattr(resp, "output", []) or []:
        if isinstance(item, ImageGenerationCall):
            # SDKs may differ: prefer getattr + log if missing
            b64 = getattr(item, "response", None)
            if not b64:
                logger.warning("ImageGenerationCall present, but no base64 payload on `response`")
            norm = NormalizedAttachment(
                type="image",
                b64=b64,
                provider_meta={
                    "provider": "openai",
                    "provider_image_call_id": getattr(item, "id", None),
                    "provider_raw_response": item.model_dump(),
                },
            )
            _attachments.append(norm)
            logger.debug(f"... image generation output normalized: {repr(norm)[:200]}")

    if _attachments:
        _messages.append(
            NormalizedAIMessage(
                role="tool",
                content="",
                tool_calls=[
                    {
                        "name": "image_generation",
                        "id": a.provider_meta.get("provider_image_call_id")
                    }
                    for a in _attachments
                ],
                attachments=_attachments,
            )
        )
        logger.debug("... image generation output(s) attached to message list")

    md_obj = getattr(_parsed, "metadata", None)

    if not md_obj:
        logger.debug("... no metadata object on parsed schema")

    count = 1
    for item in _iter_metadata_items(md_obj) or []:
        # Accept either Pydantic models or plain dicts
        if hasattr(item, "model_dump"):
            data = item.model_dump()
        elif isinstance(item, dict):
            data = item
        else:
            # Unknown object → coerce to generic
            data = {"type": "generic", "key": getattr(item, "key", "meta"), "value": getattr(item, "value", None)}

        # Ensure discriminator and key exist
        data.setdefault("type", "generic")
        data.setdefault("key", data.get("key", "meta"))

        logger.debug(f"... metafield ({count}) prepared for normalization: {data}")

        meta_obj = _META_ADAPTER.validate_python(data)
        _metadata.append(meta_obj)

        logger.debug(f"... metafield ({count}) normalized: {meta_obj}")
        count += 1

    # Attempt to serialize the provider response object
    try:
        provider_response = resp.model_dump()
    except Exception as e:
        logger.warning(f"Failed to dump response to schema: {e}")
        provider_response = None

    provider_meta = {
        "model": getattr(resp, "model", None),
        "provider": "openai",
        "provider_response_id": getattr(resp, "id", None),
        "provider_response": provider_response,
    }

    return NormalizedAIResponse(
        messages=_messages,
        metadata=_metadata,
        usage=_usage,
        provider_meta=provider_meta,
    )


# ---------- OpenAI Provider Definition -----------------------------------------------
class OpenAIProvider(ProviderBase):
    def __init__(
            self,
            api_key: str,
            timeout: float | NotGiven = NOT_GIVEN,
            name: str = "openai",
    ):
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)
        super().__init__(name=name, description="N/A")

    async def call(self, req: NormalizedAIRequest) -> NormalizedAIResponse:
        """Call OpenAI API and normalize the response."""
        logger.debug(f"provider `{self.name}` received request call")

        if req.schema_cls is not None:
            schema: ResponseTextConfigParam = build_output_schema(
                req.schema_cls)
        else:
            schema = NOT_GIVEN

        provider_tools = _adapt_tools(req.tools)
        logger.debug(f"provider `{self.name}` adapted tools: {provider_tools}")

        input_ = [
            m.model_dump(
                include={"role","content","tool_calls"},
                exclude_none=True
            ) for m in req.messages
        ]
        resp: OpenAIResponse = await self._client.responses.create(
            model=req.model or NOT_GIVEN,
            input=input_,
            text=schema or NOT_GIVEN,
            previous_response_id=req.previous_response_id or NOT_GIVEN,
            tools=provider_tools or NOT_GIVEN,
            tool_choice=req.tool_choice or NOT_GIVEN,
            max_output_tokens=req.max_output_tokens or NOT_GIVEN,
            temperature=req.temperature or NOT_GIVEN,
        )
        logger.debug(f"provider `{self.name}` received response\n(response:\t{resp})")

        return NormalizedAIResponse.normalize(
            resp=resp,
            _from=self.name,
            schema_cls=req.schema_cls,
        )

    async def stream(self, req: NormalizedAIRequest):
        raise NotImplementedError

        async with self._client.responses.stream(
                model=req.model,
                input=[m.dict(exclude_none=True) for m in req.messages],
                tools=req.tools,
                tool_choice=req.tool_choice,
                max_output_tokens=req.max_output_tokens,
                temperature=req.temperature,
        ) as stream:
            async for event in stream:
                if event.type == "delta":
                    yield NormalizedStreamChunk(delta=event.delta.content or "")
                elif event.type == "completed":
                    break


def build_from_settings(settings) -> ProviderBase:
    api_key = (getattr(settings, "OPENAI_API_KEY", None) or
               getattr(settings, "AI_API_KEY", None))
    if not api_key:
        raise RuntimeError("No OpenAI API key found. Please set OPENAI_API_KEY or AI_API_KEY in settings.")
    timeout = getattr(settings, "AI_TIMEOUT_S", 30)
    return OpenAIProvider(api_key=api_key, timeout=timeout)
