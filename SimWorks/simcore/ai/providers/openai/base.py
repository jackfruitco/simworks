# simcore/ai/providers/openai/base.py
from __future__ import annotations

import logging
import warnings
from typing import Any

from openai import NotGiven, NOT_GIVEN, AsyncOpenAI
from openai.types.responses import ResponseTextConfigParam, Response as OpenAIResponse
from openai.types.responses.response_output_item import ImageGenerationCall

from simcore.ai import build_output_schema
from simcore.ai.providers.base import ProviderBase
from simcore.ai.providers.openai.schema_overrides import OutputMetafieldItemOverride, OutputResultItemOverride, \
    OutputFeedbackEndexItemOverride
from simcore.ai.providers.openai.tools import OpenAIToolAdapter
from simcore.ai.schemas import LLMRequest, LLMResponse, AttachmentItem
from simcore.ai.schemas.output import OutputFeedbackSchema

logger = logging.getLogger(__name__)


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

    @staticmethod
    def has_schema_overrides() -> bool:
        return True

    def normalize_output_instance(self, model_instance: Any) -> Any:
        # If model_instance.metadata is one of our provider override containers, flatten it
        if model_instance is None:
            return model_instance

        metadata = getattr(model_instance, "metadata", None)

        # Import locally to avoid reference errors if overrides move to a separate module
        try:
            override_types = []
            for name in (
                    "OutputMetafieldItemOverride",
                    "OutputResultItemOverride",
                    "OutputFeedbackEndexItemOverride",
            ):
                try:
                    override_types.append(globals()[name])  # or use getattr(module, name)
                except KeyError:
                    pass

            # Handle if metadata is a single override container
            if any(isinstance(metadata, t) for t in override_types if isinstance(t, type)):
                flattened = metadata.flatten()
                return model_instance.model_copy(update={"metadata": flattened})
            # Handle if metadata is a list of override containers
            if isinstance(metadata, list) and metadata and any(
                isinstance(metadata[0], t) for t in override_types if isinstance(t, type)
            ):
                flattened = []
                for item in metadata:
                    for t in override_types:
                        if isinstance(item, t):
                            flattened.extend(item.flatten())
                            break
                        # else: skip
                return model_instance.model_copy(update={"metadata": flattened})
        except Exception:
            # If flatten fails for any reason, just return the original instance
            return model_instance

        return model_instance

    async def call(self, req: LLMRequest, timeout: float | None = None) -> LLMResponse:
        logger.debug("provider '%s':: received request call", self.name)

        logger.debug(f"provider '{self.name}':: building output schema from {req.schema_cls}")
        schema: ResponseTextConfigParam | NotGiven = (
            build_output_schema(req.schema_cls) if req.schema_cls is not None
            else NOT_GIVEN
        )

        native_tools = self._tools_to_provider(req.tools)
        if native_tools:
            logger.debug("provider '%s':: adapted tools: %s", self.name, native_tools)
        else:
            logger.debug("provider '%s':: no tools to adapt", self.name)

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
        logger.debug("provider '%s':: received response\n(response (pre-adapt):\t%s)", self.name, str(resp)[:1000])

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
