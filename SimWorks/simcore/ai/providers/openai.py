# simcore/ai/providers/openai.py
import logging

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
from pydantic import TypeAdapter

from .base import ProviderBase
from ..parsers.output_parser import maybe_parse_to_schema
from ..schemas.normalized_types import NormalizedAIMessage, NormalizedAIMetadata, NormalizedAIMetadata as MetaUnion, \
    NormalizedAIRequest, NormalizedAIResponse, NormalizedStreamChunk
from ..utils.helpers import build_output_schema


logger = logging.getLogger(__name__)


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

    if not text:
        msg = f"No output_text found in OpenAI Responses API response: {resp}"
        logger.error(msg)
        raise ValueError(msg)

    # If caller supplied a schema, try to parse strictly
    if schema_cls is not None:
        _parsed = maybe_parse_to_schema(text, schema_cls)
    else:
        _parsed = None

    if not _parsed or isinstance(_parsed, str):
        # TODO add fallback to plain text if schema fails
        raise ValueError(f"Could not parse output_text to schema: {_parsed}")

    _messages: list[NormalizedAIMessage] = []
    _metadata: list[NormalizedAIMetadata] = []

    # Parse and normalize message(s)
    for raw_msg in getattr(_parsed, "messages", []) or []:
        _messages.append(

            NormalizedAIMessage(
                role=raw_msg.role,
                content=raw_msg.content
            )
        )

    count = 1
    total = len(_messages)
    for m in _messages:
        logger.debug(f"... message ({count} of {total}) normalized: {m}")
        count += 1

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

    provider_meta = {
        "model": getattr(resp, "model", None),
        "provider": "openai"
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

        resp: OpenAIResponse = await self._client.responses.create(
            model=req.model,
            input=[m.model_dump(exclude_none=True) for m in req.messages],
            text=schema,
            # tools=req.tools,
            # tool_choice=req.tool_choice,
            max_output_tokens=req.max_output_tokens,
            # temperature=req.temperature,
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
    timeout = getattr(settings, "OPENAI_TIMEOUT_S", 30)
    return OpenAIProvider(api_key=api_key, timeout=timeout)
