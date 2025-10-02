from __future__ import annotations

import logging
import warnings
from typing import Any
from typing import get_origin, get_args

from openai import (
    AsyncOpenAI,
    NotGiven,
    NOT_GIVEN
)
from openai.types.responses import (
    Response as OpenAIResponse,
    ResponseTextConfigParam,
)
from openai.types.responses.response_output_item import ImageGenerationCall
from openai.types.responses.tool import ImageGeneration
from pydantic import Field, create_model

from .base import ProviderBase
from ..schemas import StrictBaseModel, StrictOutputSchema
from ..schemas.output_types import (
    OutputGenericMetafield, OutputPatientHistoryMetafield, OutputPatientDemographicsMetafield,
    OutputSimulationMetafield, OutputScenarioMetafield,
)
from ..schemas.types import LLMRequest, LLMResponse, AttachmentItem
from ..utils.helpers import build_output_schema

logger = logging.getLogger(__name__)


class OpenAIMetadataItem(StrictBaseModel):
    generic_metadata: list[OutputGenericMetafield] = Field(...)
    patient_history: list[OutputPatientHistoryMetafield] = Field(...)
    patient_demographics: list[OutputPatientDemographicsMetafield] = Field(...)
    simulation_metadata: list[OutputSimulationMetafield] = Field(...)
    scenario_data: list[OutputScenarioMetafield] = Field(...)

    def flatten(self) -> list[dict]:
        flat: list[dict] = []

        for items in self.model_dump().values():
            flat.extend(items)
        return flat


# --- OpenAI Tool Adapter for ToolItem DTOs ---------------------------------
class OpenAIToolAdapter(ProviderBase.ToolAdapter):
    """Adapter for OpenAI tool/function specs from/to our ToolItem DTOs."""
    provider = "openai"

    def to_provider(self, tool: "ToolItem") -> Any:  # type: ignore[name-defined]
        # Expecting kind=="image_generation" or function-based tools; adapt to OpenAI's tool schema
        # For image generation via Responses API, OpenAI uses `tools=[{"type":"image_generation"}]` variant.
        # If you use function tools, map to {"type":"function", "function": {...}}.
        if tool.kind == "image_generation":
            # Map our DTO to OpenAI ImageGeneration spec
            # `ImageGeneration` pydantic model takes fields like size, background, prompt_bias, etc.
            allowed = getattr(ImageGeneration, "model_fields", {}).keys()
            filtered = {k: v for k, v in (tool.arguments or {}).items() if k in allowed}
            return ImageGeneration(**filtered)
        # default: function tool
        return {
            "type": "function",
            "function": {
                "name": tool.function or "tool",
                "parameters": tool.arguments or {},
            },
        }

    def from_provider(self, raw: Any) -> "ToolItem":  # type: ignore[name-defined]
        from simcore.ai.schemas.types import ToolItem  # local import to avoid cycles
        # OpenAI returns {"type":"function", "function": {...}} or an ImageGeneration model
        if isinstance(raw, ImageGeneration):
            return ToolItem(kind="image_generation", function="generate", arguments=raw.model_dump())
        if isinstance(raw, dict) and raw.get("type") == "function":
            fn = raw.get("function") or {}
            return ToolItem(kind="function", function=fn.get("name"), arguments=fn.get("parameters") or {})
        # Fallback generic
        return ToolItem(kind=str(getattr(raw, "type", "function")), function=getattr(raw, "name", None),
                        arguments=getattr(raw, "parameters", {}) or {})

# ---------- OpenAI Provider Definition -----------------------------------------------
class OpenAIProvider(ProviderBase):
    def __init__(
            self,
            api_key: str,
            timeout: float | NotGiven = NOT_GIVEN,
            name: str = "openai",
    ):
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)
        self.timeout = timeout
        self.api_key = api_key
        super().__init__(name=name, description="OpenAI Responses API")
        # Register tools adapter
        self.set_tool_adapter(OpenAIToolAdapter())

    def _schema_to_provider(self, schema_cls: type) -> type:
        """Return a provider-specialized schema where `metadata` is an object
        (`OpenAIMetadataItem`) whose **inner properties are all required**.
        This avoids OpenAI's schema validator complaining about missing `required`
        for every property on the object.
        Uses model_fields to avoid forward-ref strings in __annotations__.
        """
        try:
            field = getattr(schema_cls, "model_fields", {}).get("metadata")
            if not field:
                return schema_cls
            ann = getattr(field, "annotation", None)
            from typing import get_origin
            origin = get_origin(ann)
            if origin is list:
                Specialized = create_model(
                    schema_cls.__name__ + "OpenAI",
                    __base__=schema_cls,
                    metadata=(OpenAIMetadataItem, ...),
                )
                return Specialized
        except Exception:
            # Fall back silently to the original schema class if anything goes wrong
            pass
        return schema_cls

    def normalize_output_instance(self, model_instance: Any) -> Any:
        # If model_instance.metadata is OpenAIMetadataItem, flatten it
        if model_instance is None:
            return model_instance
        metadata = getattr(model_instance, "metadata", None)
        if isinstance(metadata, OpenAIMetadataItem):
            flattened = metadata.flatten()
            return model_instance.model_copy(update={"metadata": flattened})
        return model_instance

    async def call(self, req: LLMRequest, timeout: float | None = None) -> LLMResponse:
        logger.debug("provider `%s`:: received request call", self.name)

        schema: ResponseTextConfigParam | NotGiven
        if req.schema_cls is not None:
            specialized = self.specialize_output_schema(req.schema_cls)
            schema = build_output_schema(specialized) if specialized is not None else NOT_GIVEN
        else:
            schema = NOT_GIVEN

        native_tools = self._tools_to_provider(req.tools)
        if native_tools:
            logger.debug("provider `%s`:: adapted tools: %s", self.name, native_tools)
        else:
            logger.debug("provider `%s`:: no tools to adapt", self.name)

        input_ = [
            m.model_dump(include={"role", "content", "tool_calls"}, exclude_none=True)
            for m in req.messages
        ]

        resp: OpenAIResponse = await self._client.responses.create(
            model=req.model or NOT_GIVEN,
            input=input_,
            text=schema or NOT_GIVEN,
            previous_response_id=req.previous_response_id or NOT_GIVEN,
            tools=native_tools or NOT_GIVEN,
            tool_choice=req.tool_choice or NOT_GIVEN,
            max_output_tokens=req.max_output_tokens or NOT_GIVEN,
            timeout=timeout or self.timeout or NOT_GIVEN,
            # temperature=req.temperature or NOT_GIVEN,
        )
        logger.debug("provider `%s`:: received response\n(response:\t%s)", self.name, str(resp)[:200])

        return self.adapt_response(resp, schema_cls=req.schema_cls)

    async def stream(self, req: LLMRequest):  # pragma: no cover - not yet implemented
        raise NotImplementedError

    # --- ProviderBase hook implementations ---------------------------------
    def _extract_text(self, resp: OpenAIResponse) -> str | None:
        return getattr(resp, "output_text", None)

    def _extract_outputs(self, resp: OpenAIResponse):
        return getattr(resp, "output", []) or []

    def _is_image_output(self, item: Any) -> bool:
        return isinstance(item, ImageGenerationCall)

    def _build_attachment(self, item: Any) -> AttachmentItem | None:
        if not isinstance(item, ImageGenerationCall):
            return None
        b64 = getattr(item, "result", None)
        if not b64:
            logger.warning("ImageGenerationCall present, but no base64 `result`")
            return None
        return AttachmentItem(
            kind="image",
            b64=b64,
            provider_meta={
                "provider": self.name,
                "provider_image_call_id": getattr(item, "id", None),
                "provider_raw_response": item.model_dump(),
            },
        )

    def _extract_usage(self, resp: OpenAIResponse) -> dict:
        usage = getattr(resp, "usage", None)
        if not usage:
            return {}

        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)

        itd = getattr(usage, "input_tokens_details", None)
        otd = getattr(usage, "output_tokens_details", None)

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "input_tokens_details": getattr(itd, "cached_tokens", None) if itd else None,
            "output_tokens_details": getattr(otd, "reasoning_tokens", None) if otd else None,
        }

    def _extract_provider_meta(self, resp: OpenAIResponse) -> dict:
        meta = {
            "model": getattr(resp, "model", None),
            "provider": self.name,
            "provider_response_id": getattr(resp, "id", None),
        }
        if logger.isEnabledFor(logging.DEBUG):
            try:
                meta["provider_response"] = resp.model_dump()
            except Exception:
                meta["provider_response"] = None
        return meta

    @staticmethod
    def _coerce_usage(usage_obj) -> dict:
        """
        Coerce OpenAI ResponseUsage into the flat dict shape our NormalizedAIResponse expects.
        Falls back to None for any missing fields.
        """
        # TODO deprecated -- remove method
        warnings.warn("Pending Deprecation -- use _extract_usage() instead", DeprecationWarning, stacklevel=2)
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


def build_from_settings(settings) -> ProviderBase:
    api_key = (getattr(settings, "OPENAI_API_KEY", None) or
               getattr(settings, "AI_API_KEY", None))
    if not api_key:
        raise RuntimeError("No OpenAI API key found. Please set OPENAI_API_KEY or AI_API_KEY in settings.")
    timeout = getattr(settings, "AI_TIMEOUT_S", 30)
    return OpenAIProvider(api_key=api_key, timeout=timeout)
