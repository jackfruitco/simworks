"""Self-contained OpenAI Responses provider.

The original implementation depended on the real ``openai`` client. For a
lightweight, test-friendly core we keep a minimal stub client that can be
monkeypatched in tests while preserving the provider contract.
"""
from __future__ import annotations

import logging
from typing import Any, Final, Literal, Optional

from orchestrai.components.providerkit import BaseProvider
from orchestrai.components.providerkit.exceptions import ProviderError
from orchestrai.decorators import provider_backend
from orchestrai.tracing import flatten_context as _flatten_context, service_span, service_span_sync
from orchestrai.types import Request, Response
from .output_adapters import ImageGenerationOutputAdapter
from .tools import OpenAIToolAdapter

logger = logging.getLogger(__name__)

__all__ = ["OpenAIResponsesProvider"]

PROVIDER_NAME: Final[Literal["openai"]] = "openai"
API_SURFACE: Final[Literal["responses"]] = "responses"
API_VERSION: Final[None] = None


class _StubResponses:
    async def create(self, **_: Any):  # pragma: no cover - default path unused in tests
        raise ProviderError("OpenAI client not configured; monkeypatch in tests")


class AsyncOpenAI:
    def __init__(self, *, api_key: str | None, base_url: str | None, timeout: int | None):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.responses = _StubResponses()


NOT_GIVEN = object()


@provider_backend(namespace=PROVIDER_NAME, kind=API_SURFACE, name="backend")
class OpenAIResponsesProvider(BaseProvider):
    """Minimal OpenAI Responses API backend."""

    def __init__(
        self,
        *,
        alias: str,
        provider: str | None = PROVIDER_NAME,
        api_surface: Literal["responses"] | None = API_SURFACE,
        api_version: Literal[None] | None = API_VERSION,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        model: str | None = None,
        timeout_s: int = 60,
        profile: str | None = None,
        slug: Optional[str] = None,
        description: str | None = None,
        api_key_required: bool | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            alias=alias,
            provider=provider or PROVIDER_NAME,
            api_key_required=api_key_required,
            api_key=api_key,
            description=description,
            slug=slug,
            profile=profile,
            namespace=provider or PROVIDER_NAME,
            kind=api_surface or API_SURFACE,
            name="backend",
            **kwargs,
        )
        self.base_url = base_url
        self.default_model = default_model if default_model is not None else model
        self.timeout_s = timeout_s
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_s)
        self.set_tool_adapter(OpenAIToolAdapter())
        self._output_adapters = [ImageGenerationOutputAdapter()]

    async def healthcheck(self, *, timeout: float | None = None) -> tuple[bool, str]:
        # Lightweight stubbed healthcheck
        return True, "openai stub ready"

    async def call(self, req: Request, timeout: float | None = None) -> Response:
        async with service_span(
            "simcore.client.call",
            attributes={
                "simcore.provider_name": self.provider,
                "simcore.client_name": getattr(self, "provider", self.__class__.__name__),
                "simcore.model": req.model or self.default_model or "<unspecified>",
                "simcore.stream": bool(getattr(req, "stream", False)),
                "simcore.request.correlation_id": str(getattr(req, "correlation_id", "")) or None,
                "simcore.codec": getattr(req, "codec", None),
                **_flatten_context(getattr(req, "context", {}) or {}),
            },
        ):
            native_tools = self._tools_to_provider(req.tools)
            input_ = [m.model_dump(include={"role", "content"}, exclude_none=True) for m in req.input]
            model_name = req.model or self.default_model or "gpt-4o-mini"
            response_format = getattr(req, "provider_response_format", None) or getattr(req, "response_schema_json", None)

            resp = await self._client.responses.create(
                model=model_name,
                input=input_,
                previous_response_id=req.previous_response_id or NOT_GIVEN,
                tools=native_tools or NOT_GIVEN,
                tool_choice=req.tool_choice or NOT_GIVEN,
                max_output_tokens=req.max_output_tokens or NOT_GIVEN,
                timeout=timeout or self.timeout_s or NOT_GIVEN,
                text=response_format or NOT_GIVEN,
            )
            return self.adapt_response(resp, output_schema_cls=req.response_schema)

    async def stream(self, req: Request):  # pragma: no cover - streaming not implemented
        raise ProviderError("Streaming not implemented in stub provider")

    # Provider hooks --------------------------------------------------
    def _extract_text(self, resp: Any) -> Optional[str]:
        return getattr(resp, "output_text", None) or getattr(resp, "text", None) or None

    def _extract_outputs(self, resp: Any):
        return getattr(resp, "output", None) or []

    def _is_image_output(self, item: Any) -> bool:
        return hasattr(item, "result") and hasattr(item, "mime_type")

    def _extract_usage(self, resp: Any) -> dict:
        usage = getattr(resp, "usage", None) or {}
        return usage if isinstance(usage, dict) else getattr(usage, "__dict__", {}) or {}

    def _extract_provider_meta(self, resp: Any) -> dict:
        base = {
            "model": getattr(resp, "model", None),
            "id": getattr(resp, "id", None),
        }
        try:
            base["raw"] = resp.model_dump() if hasattr(resp, "model_dump") else None
        except Exception:  # pragma: no cover - defensive
            base["raw"] = None
        return base

    def _normalize_tool_output(self, item: Any):
        with service_span_sync("simcore.tools.handle_output", attributes={"simcore.provider_name": self.provider}):
            for adapter in getattr(self, "_output_adapters", []):
                result = adapter.adapt(item)
                if result is not None:
                    return result
        return None
