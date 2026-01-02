"""OpenAI Responses API request builder.

This module builds JSON-serializable payloads for the OpenAI Responses API from
OrchestrAI's internal Request objects. It handles:
- Message normalization
- Tool declarations
- Response format/schema attachment
- Metadata serialization

All OpenAI-specific request formatting logic is centralized here.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Sequence

from orchestrai.types import Request

logger = logging.getLogger(__name__)

__all__ = ["build_responses_request"]


def _json_safe(value: Any) -> Any:
    """Return a JSON-serializable clone of ``value`` or raise ``ValueError``.

    The clone is produced via ``json.dumps``/``json.loads`` to guarantee the
    result can be serialized without a custom encoder.
    """

    try:
        return json.loads(json.dumps(value))
    except TypeError as exc:  # pragma: no cover - defensive conversion
        raise ValueError("OpenAI Responses request payload is not JSON serializable") from exc


def _normalize_input(messages: Sequence[Any]) -> list[dict[str, Any]]:
    """Normalize message inputs into JSON-safe dicts."""

    normalized: list[dict[str, Any]] = []
    for item in messages:
        if hasattr(item, "model_dump"):
            payload = item.model_dump(include={"role", "content"}, exclude_none=True)
        elif isinstance(item, Mapping):
            payload = dict(item)
        else:  # pragma: no cover - defensive branch
            raise TypeError(f"Unsupported message type for OpenAI Responses request: {type(item)!r}")

        normalized.append(_json_safe(payload))

    return normalized


def _extract_tool_declarations(provider_tools: Sequence[Any] | None) -> list[str]:
    """Collect a stable list of tool identifiers for diagnostics."""

    declarations: list[str] = []
    for tool in provider_tools or []:
        name: str | None = None
        if isinstance(tool, Mapping):
            fn = tool.get("function")
            if isinstance(fn, Mapping):
                name = fn.get("name") or None
            if name is None:
                raw_name = tool.get("name")
                name = raw_name if isinstance(raw_name, str) else None
            if name is None:
                raw_type = tool.get("type")
                name = raw_type if isinstance(raw_type, str) else None
        if name:
            declarations.append(str(name))

    # preserve order but drop duplicates
    seen: dict[str, None] = {}
    for item in declarations:
        seen.setdefault(item, None)
    return list(seen.keys())


def build_responses_request(
    *,
    req: Request,
    model: str,
    provider_tools: Sequence[Any] | None = None,
    response_format: Mapping[str, Any] | None = None,
    timeout: float | int | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe request payload for the OpenAI Responses API.

    Args:
        req: OrchestrAI Request object
        model: Model name (e.g., "gpt-4o-mini")
        provider_tools: Provider-specific tool definitions
        response_format: Optional response format override
        timeout: Request timeout in seconds

    Returns:
        JSON-serializable dict ready for OpenAI Responses API
    """

    resolved_response_format: Any = (
        response_format
        if response_format is not None
        else getattr(req, "provider_response_format", None) or getattr(req, "response_schema_json", None)
    )

    logger.debug(f"[RequestBuilder] response_format param: {type(response_format)}")
    logger.debug(f"[RequestBuilder] req.provider_response_format: {type(getattr(req, 'provider_response_format', None))}")
    logger.debug(f"[RequestBuilder] req.response_schema_json: {type(getattr(req, 'response_schema_json', None))}")

    if isinstance(resolved_response_format, dict):
        has_wrapper = 'json_schema' in resolved_response_format
        schema_type = resolved_response_format.get('type') if has_wrapper else resolved_response_format.get('title')
        logger.debug(f"[RequestBuilder] resolved_response_format has wrapper: {has_wrapper}, schema_type: {schema_type}")
    else:
        logger.debug(f"[RequestBuilder] resolved_response_format is not a dict: {type(resolved_response_format)}")

    metadata: dict[str, Any] = {}
    codec_identity = getattr(req, "codec_identity", None)
    if codec_identity:
        metadata["codec_identity"] = str(codec_identity)

    tool_declarations = _extract_tool_declarations(provider_tools)
    if tool_declarations:
        metadata["tools_declared"] = tool_declarations

    if resolved_response_format is not None:
        metadata.setdefault("response_format", "text")

    payload = {
        "model": model,
        "input": _normalize_input(getattr(req, "input", []) or []),
        "previous_response_id": getattr(req, "previous_response_id", None),
        "tools": _json_safe(provider_tools) if provider_tools else None,
        "tool_choice": getattr(req, "tool_choice", None),
        "max_output_tokens": getattr(req, "max_output_tokens", None),
        "timeout": timeout,
        "text": resolved_response_format,
    }

    logger.debug(f"[RequestBuilder] Final payload text field has wrapper: {isinstance(payload.get('text'), dict) and 'json_schema' in payload.get('text', {})}")

    if metadata:
        # OpenAI expects metadata.orchestrai to be a string, not an object
        payload["metadata"] = {"orchestrai": json.dumps(metadata)}

    # Final check: ensure the overall payload is JSON-serializable
    return _json_safe(payload)
