"""OpenAI Responses provider backed by the real client when available."""
from __future__ import annotations

import logging
import os
from importlib import import_module
from typing import Any, Final, Literal, Optional, cast

from orchestrai.components.providerkit import BaseProvider
from orchestrai.components.providerkit.exceptions import ProviderError
from orchestrai.decorators import provider_backend
from orchestrai.conf import DEFAULTS
from orchestrai.tracing import flatten_context as _flatten_context, service_span, service_span_sync
from orchestrai.types import Request, Response
from orchestrai.components.services.providers.openai_responses.build import build_responses_request
from .output_adapters import ImageGenerationOutputAdapter
from .tools import OpenAIToolAdapter
from orchestrai.utils import clean_kwargs

logger = logging.getLogger(__name__)

__all__ = ["OpenAIResponsesProvider"]

PROVIDER_NAME: Final[Literal["openai"]] = "openai"
API_SURFACE: Final[Literal["responses"]] = "responses"
API_VERSION: Final[None] = None
DEFAULT_TIMEOUT_S: Final[int | float] = cast(int | float, DEFAULTS["PROVIDER_DEFAULT_TIMEOUT"])
DEFAULT_MODEL: Final[str] = cast(str, DEFAULTS["PROVIDER_DEFAULT_MODEL"])


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
        timeout_s: int | float | None = None,
        client: Any | None = None,
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
        self.default_model = default_model if default_model is not None else (model or DEFAULT_MODEL)
        self.timeout_s = timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = self._resolve_client(client)
        self.set_tool_adapter(OpenAIToolAdapter())
        self._output_adapters = [ImageGenerationOutputAdapter()]

    def _resolve_client(self, client: Any | None) -> Any:
        if client is not None:
            return client

        if not self.api_key:
            return None

        try:
            openai_module = import_module("openai")
        except ModuleNotFoundError:
            logger.debug("OpenAI package not available; client will remain unset")
            return None

        client_cls = getattr(openai_module, "AsyncOpenAI", None)
        if client_cls is None:
            logger.debug("openai.AsyncOpenAI not found; client will remain unset")
            return None

        return client_cls(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_s)

    async def healthcheck(self, *, timeout: float | None = None) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Missing OpenAI API key (set ORCA_PROVIDER_API_KEY or OPENAI_API_KEY)"

        if self._client is None:
            return False, "OpenAI client unavailable; install the 'openai' package or inject a client"

        return True, "OpenAI client ready"

    async def call(self, req: Request, timeout: float | None = None) -> Response:
        if not self.api_key:
            raise ProviderError("OpenAI API key is required (set ORCA_PROVIDER_API_KEY or OPENAI_API_KEY)")

        if self._client is None:
            raise ProviderError("OpenAI client not available; install the 'openai' package or inject a client")

        async with service_span(
            "orchestrai.client.call",
            attributes={
                "orchestrai.provider_name": self.provider,
                "orchestrai.client_name": getattr(self, "provider", self.__class__.__name__),
                "orchestrai.model": req.model or self.default_model or "<unspecified>",
                "orchestrai.stream": bool(getattr(req, "stream", False)),
                "orchestrai.request.correlation_id": str(getattr(req, "correlation_id", "")) or None,
                "orchestrai.codec": getattr(req, "codec", None),
                **_flatten_context(getattr(req, "context", {}) or {}),
            },
        ):
            native_tools = self._tools_to_provider(req.tools)
            model_name = req.model or self.default_model or DEFAULT_MODEL
            timeout_s = timeout if timeout is not None else self.timeout_s

            raw_kwargs = build_responses_request(
                req=req,
                model=model_name,
                provider_tools=native_tools or None,
                response_format=getattr(req, "provider_response_format", None)
                or getattr(req, "response_schema_json", None),
                timeout=timeout_s,
            )

            resp = await self._client.responses.create(**clean_kwargs(raw_kwargs))
            return self.adapt_response(resp, output_schema_cls=req.response_schema)

    async def stream(self, req: Request):  # pragma: no cover - streaming not implemented
        raise ProviderError("Streaming not implemented for OpenAI responses provider")

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
        with service_span_sync("orchestrai.tools.handle_output", attributes={"orchestrai.provider_name": self.provider}):
            for adapter in getattr(self, "_output_adapters", []):
                result = adapter.adapt(item)
                if result is not None:
                    return result
        return None
