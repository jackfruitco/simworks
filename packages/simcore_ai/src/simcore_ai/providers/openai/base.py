# simcore_ai/providers/openai/base.py
from __future__ import annotations

import logging
from uuid import uuid4
from typing import Any, Final, Literal

from openai import NotGiven, NOT_GIVEN, AsyncOpenAI
from openai.types.responses import Response as OpenAIResponse
from openai.types.responses.response_output_item import ImageGenerationCall

from ..base import BaseProvider
from ..openai.tools import OpenAIToolAdapter
from ...types.dtos import LLMRequest, LLMResponse
from ...types.tools import LLMToolCall
from ...types.dtos import LLMToolResultPart

logger = logging.getLogger(__name__)

PROVIDER_NAME: Final[Literal["openai"]] = "openai"

class OpenAIProvider(BaseProvider):
    def __init__(
            self,
            api_key: str,
            timeout: float | NotGiven = NOT_GIVEN,
            name: str = PROVIDER_NAME,
    ):
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)
        self.timeout = timeout
        self.api_key = api_key
        super().__init__(name=name, description="OpenAI Responses API")
        # Register tools adapter
        self.set_tool_adapter(OpenAIToolAdapter())

    def _wrap_schema(self, compiled_schema: dict, meta: dict | None = None) -> dict | None:
        if not compiled_schema:
            return None
        meta = meta or {}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": meta.get("name", "response"),
                "schema": compiled_schema,
                "strict": bool(meta.get("strict", True)),
            },
        }

    def _normalize_tool_output(self, item: Any):
        """
        Map OpenAI Responses output items into (LLMToolCall, LLMToolResultPart).
        Currently supports ImageGenerationCall; extend for other tool types as needed.
        """
        if isinstance(item, ImageGenerationCall):
            call_id = getattr(item, "id", None) or str(uuid4())
            b64 = getattr(item, "result", None)
            mime = getattr(item, "mime_type", None) or "image/png"
            return (
                LLMToolCall(call_id=call_id, name="image_generation", arguments={}),
                LLMToolResultPart(call_id=call_id, mime_type=mime, data_b64=b64),
            )
        return None

    async def call(self, req: LLMRequest, timeout: float | None = None) -> LLMResponse:
        logger.debug("provider '%s':: received request call", self.name)

        native_tools = self._tools_to_provider(req.tools)
        if native_tools:
            logger.debug("provider '%s':: adapted tools: %s", self.name, native_tools)
        else:
            logger.debug("provider '%s':: no tools to adapt", self.name)

        input_ = [m.model_dump(include={"role", "content"}, exclude_none=True) for m in req.messages]

        resp: OpenAIResponse = await self._client.responses.create(
            model=req.model or NOT_GIVEN,
            input=input_,
            previous_response_id=req.previous_response_id or NOT_GIVEN,
            tools=native_tools or NOT_GIVEN,
            tool_choice=req.tool_choice or NOT_GIVEN,
            max_output_tokens=req.max_output_tokens or NOT_GIVEN,
            timeout=timeout or self.timeout or NOT_GIVEN,
            response_format=req.response_format or NOT_GIVEN,
        )
        logger.debug("provider '%s':: received response\n(response (pre-adapt):\t%s)", self.name, str(resp)[:1000])

        return self.adapt_response(resp, schema_cls=req.response_format_cls)

    async def stream(self, req: LLMRequest):  # pragma: no cover - not yet implemented
        raise NotImplementedError

    # --- BaseProvider hook implementations ---------------------------------
    def _extract_text(self, resp: OpenAIResponse) -> str | None:
        return getattr(resp, "output_text", None)

    def _extract_outputs(self, resp: OpenAIResponse):
        return getattr(resp, "output", []) or []

    def _is_image_output(self, item: Any) -> bool:
        return isinstance(item, ImageGenerationCall)

    # def _build_attachment(self, item: Any) -> AttachmentItem | None:
    #     if not isinstance(item, ImageGenerationCall):
    #         return None
    #     b64 = getattr(item, "result", None)
    #     if not b64:
    #         logger.warning("ImageGenerationCall present, but no base64 `result`")
    #         return None
    #     return AttachmentItem(
    #         kind="image",
    #         b64=b64,
    #         provider_meta={
    #             "provider": self.name,
    #             "provider_image_call_id": getattr(item, "id", None),
    #             "provider_raw_response": item.model_dump(),
    #         },
    #     )

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
