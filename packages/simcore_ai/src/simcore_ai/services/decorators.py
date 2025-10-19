from typing import Optional, Any, TypeVar, overload, cast
from collections.abc import Sequence, Callable
from simcore_ai.services import BaseLLMService

TFunc = TypeVar("TFunc", bound=Callable[..., Any])

@overload
def llm_service(_func: None = None, *, origin: Optional[str] = ..., bucket: Optional[str] = ..., name: Optional[str] = ..., codec: Optional[str] = ..., prompt_plan: Optional[Sequence[tuple[str, str]]] = ...) -> Callable[[TFunc], type]: ...
@overload
def llm_service(_func: TFunc, *, origin: Optional[str] = ..., bucket: Optional[str] = ..., name: Optional[str] = ..., codec: Optional[str] = ..., prompt_plan: Optional[Sequence[tuple[str, str]]] = ...) -> type: ...

def llm_service(
    _func: Optional[Callable[..., Any]] = None,
    *,
    origin: Optional[str] = None,
    bucket: Optional[str] = None,
    name: Optional[str] = None,
    codec: Optional[str] = None,
    prompt_plan: Optional[Sequence[tuple[str, str]]] = None,
):
    """
    Decorate a simple async function and expose it as a `BaseLLMService` subclass.

    Usages:
        @llm_service
        async def generate(simulation, slim): ...

        @llm_service(origin="chatlab", bucket="patient", codec="default", prompt_plan=(("initial","hotwash"),))
        async def generate(simulation, slim): ...

    In bare form, identity defaults are inferred from the function's module/name.
    In called form, `origin` and `bucket` must be non-empty strings.
    """

    def _infer_from_func(func: Callable[..., Any]) -> tuple[str, str, str, str, tuple[tuple[str, str], ...]]:
        mod = getattr(func, "__module__", "") or ""
        parts = [p for p in mod.split(".") if p]
        inferred_origin = parts[0] if parts else "simcore"
        inferred_bucket = parts[-1] if parts else func.__name__
        svc_name = name or func.__name__
        resolved_codec = codec or "default"
        resolved_plan = tuple(prompt_plan) if prompt_plan is not None else tuple()
        return inferred_origin, inferred_bucket, svc_name, resolved_codec, resolved_plan

    def _validate_explicit() -> tuple[str, str, str, str, tuple[tuple[str, str], ...]]:
        if not origin or not isinstance(origin, str):
            raise TypeError("llm_service: 'origin' must be a non-empty string when provided explicitly")
        if not bucket or not isinstance(bucket, str):
            raise TypeError("llm_service: 'bucket' must be a non-empty string when provided explicitly")
        svc_name = name or ""
        resolved_codec = codec or "default"
        resolved_plan = tuple(prompt_plan) if prompt_plan is not None else tuple()
        return origin, bucket, svc_name, resolved_codec, resolved_plan  # type: ignore[return-value]

    def _apply(func: Callable[..., Any]) -> type:
        # Determine identity/config either from explicit args or inference
        if origin is None and bucket is None:
            _origin, _bucket, _name, _codec, _plan = _infer_from_func(func)
        else:
            _origin, _bucket, _name, _codec, _plan = _validate_explicit()
            if not _name:
                _name = func.__name__

        class _FnServiceLLMService(BaseLLMService):
            """Auto-generated service wrapper for function-level LLM services."""

            async def on_success(self, simulation, slim):
                # If the function expects (simulation, slim), pass both; else do nothing.
                f = func
                code = getattr(f, "__code__", None)
                if code is not None and getattr(code, "co_argcount", 0) >= 2:
                    return await f(simulation, slim)
                return None

        # Bind class-level identity/config from decorator args (closure-safe)
        _FnServiceLLMService.origin = _origin
        _FnServiceLLMService.bucket = _bucket
        _FnServiceLLMService.name = _name
        _FnServiceLLMService.codec_name = _codec
        _FnServiceLLMService.prompt_plan = _plan
        _FnServiceLLMService.__name__ = f"{func.__name__}_Service"
        _FnServiceLLMService.__module__ = getattr(func, "__module__", __name__)
        return _FnServiceLLMService

    # Bare form: @llm_service
    if _func is not None:
        if not callable(_func):
            raise TypeError("llm_service: decorated object must be callable")
        return _apply(cast(Callable[..., Any], _func))

    # Called form: @llm_service(...)
    return _apply