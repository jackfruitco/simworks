#
# Provider-agnostic DTOs
try:
    from simcore.ai.dtos import LLMRequest, MessageItem  # preferred path
except Exception:
    try:
        from simcore.ai.types import LLMRequest, MessageItem  # fallback path
    except Exception:
        LLMRequest = None  # type: ignore
        MessageItem = None  # type: ignore
import logging
import warnings
import asyncio
import time
from typing import Any, Iterable, Sequence, Type
def _coerce_usage(usage: Any) -> dict | None:
    if usage is None:
        return None
    try:
        # pydantic or dataclass style
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if hasattr(usage, "dict"):
            return usage.dict()
    except Exception:
        pass
    # Fallback: ensure it's JSON-ish
    if isinstance(usage, dict):
        return usage
    try:
        return dict(usage)
    except Exception:
        return {"raw": str(usage)}

from django.conf import settings
from openai.types.responses import Response as OpenAIResponse
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import BaseModel, ValidationError

from simcore.ai import get_ai_client

from simai.models import ResponseType
from simai.response_schema import PatientInitialSchema, PatientResultsSchema, SimulationFeedbackSchema
from simai.response_schema import PatientReplySchema

logger = logging.getLogger(__name__)

MODEL_MAP: dict[ResponseType, type[PatientReplySchema | PatientInitialSchema]] = {
    ResponseType.INITIAL: PatientInitialSchema,
    ResponseType.REPLY:  PatientReplySchema,
    ResponseType.PATIENT_RESULTS: PatientResultsSchema,
    ResponseType.FEEDBACK: SimulationFeedbackSchema,
}

def build_output_schema(model: Type[BaseModel]) -> ResponseTextConfigParam:
    """
    Build the `text` param for openai.responses.create() that
    tells the API to emit JSON matching `model`’s schema.

    :param model: The Pydantic model class to generate a schema for.
    :type model: Type[BaseModel]

    :return: The `text` param for openai.responses.create().
    :rtype: ResponseTextConfigParam
    """
    # TODO consider if this is OpenAI Provider-specific or agnostic
    # TODO consider if the schemas themselves should be OpenAI Provider-specific
    return {
        "format": {
            "type": "json_schema",
            "name": model.__name__,
            "schema": model.model_json_schema(),
        }
    }

def build_response_text_param(model: Type[BaseModel]) -> ResponseTextConfigParam:
    """Alias for build_output_schema() backwards compatibility."""
    warnings.warn(
        "build_response_text_param() is deprecated, use build_output_schema() instead",
        DeprecationWarning)
    return build_output_schema(model)


def maybe_coerce_to_schema(
    response: OpenAIResponse,
    response_type: ResponseType
) -> PatientInitialSchema | PatientReplySchema | SimulationFeedbackSchema | str:
    """
    Convert `response.output_text` into a Pydantic model for INITIAL/REPLY types.

    Args:
        response: The OpenAIResponse object.
        response_type: One of ResponseType.INITIAL or REPLY to pick parsing.

    Returns:
        A PatientInitialOutputSchema or PatientReplyOutputSchema instance if parsed;
        otherwise the raw `output_text` string.
    """
    warnings.warn(
        "maybe_coerce_to_schema() is deprecated, "
        "use simcore.ai.parsers.output_parser instead",
        DeprecationWarning
    )

    ModelClass = MODEL_MAP.get(response_type)
    if not ModelClass:
        logger.debug(f"No pydantic schema found for {response_type.label} output, "
                     f"using combined `output_text` instead")
        return response.output_text

    try:
        logger.debug(f"Validating {response_type.label} output against schema `{ModelClass.__name__}`")
        return ModelClass.model_validate_json(response.output_text)
    except ValidationError as e:
        logger.error("Schema validation failed for %s: %s", response_type.label, e)
        return response.output_text

async def compare_models(
    messages: Sequence[MessageItem | dict[str, Any]],
    models: Iterable[str],
    *,
    text: ResponseTextConfigParam | None = None,
    temperature: float = 0.2,
    seed: int | None = 1337,
    metadata: dict[str, Any] | None = None,
    max_concurrency: int = 8,
    include_default_model: bool = True,
) -> list[dict[str, Any]]:
    """
    Run the same LLM request against multiple models in parallel using the configured AI provider.

    Each model receives the same message sequence, parameters, and output schema.
    This function leverages the project's base provider client (via `get_ai_client()`)
    so provider routing, error handling, and logging behave identically to normal calls.

    Args:
        messages: Developer/user/system message list to send as `input`.
        models: Iterable of model IDs to compare (e.g., ["gpt-5", "gpt-4o", "gpt-4o-mini"]).
        text: Optional `text` parameter (see `build_output_schema`) enforcing JSON/schema output.
        temperature: Sampling temperature shared by all models.
        seed: Optional seed to improve reproducibility across supported models.
        metadata: Optional metadata dict forwarded to the provider for tracing and analytics.

    Returns:
        A list of dictionaries, one per model:
            {
              "model": str,
              "id": str | None,
              "ok": bool,
              "output_text": str | None,
              "usage": dict | None,
              "error": str | None,
            }

    Notes:
        - Runs all models concurrently using asyncio.gather().
        - Automatically includes `settings.AI_DEFAULT_MODEL` if not listed.
        - Designed for evaluation and benchmarking of multiple models under identical conditions.
        - Limits concurrent calls via `max_concurrency` to avoid provider throttling.
        - Set `include_default_model=False` to prevent auto-appending `settings.AI_DEFAULT_MODEL`.
    """

    sem = asyncio.Semaphore(max(1, max_concurrency))

    async def _run(model: str) -> dict[str, Any]:
        await sem.acquire()
        t0 = time.perf_counter()
        try:
            client = get_ai_client()
            try:
                # Build a provider-agnostic LLMRequest using MessageItem DTOs.
                dto_messages = [
                    (MessageItem(**m) if isinstance(m, dict) else m)
                    for m in messages
                ] if MessageItem else messages  # fallback to raw messages if DTOs unavailable
                req = LLMRequest(  # type: ignore[arg-type]
                    model=model,
                    messages=dto_messages,
                    temperature=temperature,
                    text=text,
                    seed=seed,
                    metadata=metadata,
                ) if LLMRequest else {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "text": text,
                    "seed": seed,
                    "metadata": metadata,
                }
                # Prefer calling with a single request object if supported
                try:
                    resp = await client.call(req)
                except TypeError:
                    # Fallback to kwargs form for older providers
                    resp = await client.call(
                        model=model,
                        input=messages,
                        temperature=temperature,
                        text=text,
                        seed=seed,
                        metadata=metadata,
                    )
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "model": model,
                    "id": getattr(resp, "id", None),
                    "ok": True,
                    "output_text": getattr(resp, "output_text", None),
                    "usage": _coerce_usage(getattr(resp, "usage", None)),
                    "latency_ms": round(latency_ms, 2),
                    "error": None,
                }
            except Exception as e:
                logger.exception("compare_models: model %s failed", model)
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "model": model,
                    "id": None,
                    "ok": False,
                    "output_text": None,
                    "usage": None,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e),
                }
        finally:
            try:
                sem.release()
            except Exception:
                pass

    # Normalize and optionally include the default model; de-duplicate while preserving order
    models = list(models)
    if include_default_model:
        default_model = getattr(settings, "AI_DEFAULT_MODEL", None)
        if default_model:
            models.append(default_model)
    seen = set()
    deduped: list[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            deduped.append(m)
    models = deduped

    tasks = [_run(m) for m in models]
    return await asyncio.gather(*tasks)


def compare_models_sync(
    messages: Sequence[dict[str, Any]],
    models: Iterable[str],
    *,
    text: ResponseTextConfigParam | None = None,
    temperature: float = 0.2,
    seed: int | None = 1337,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Synchronous wrapper around `compare_models` for call sites that are not async.
    """
    return asyncio.run(
        compare_models(
            messages,
            models,
            text=text,
            temperature=temperature,
            seed=seed,
            metadata=metadata,
        )
    )
# --- END compare_models additions ---