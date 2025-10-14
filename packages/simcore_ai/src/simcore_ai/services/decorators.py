from typing import Sequence, Callable
from .base import BaseLLMService


def llm_service(*, origin: str, bucket: str, name: str, codec: str, prompt_plan: Sequence[tuple[str, str]]):
    """
    Decorate a simple async function and expose it as an BaseLLMService subclass.
    The returned class inherits retry/telemetry behavior from BaseLLMService.
    - origin: producer/project ('simcore', 'trainerlab', ...)
    - bucket: functional group ('feedback', 'triage', ...)
    - name:   concrete operation ('generate-initial', ...)
    """
    def wrap(func: Callable):
        class _FnServiceLLMService(BaseLLMService):
            async def on_success(self, simulation, slim):
                if func.__code__.co_argcount >= 2:
                    return await func(simulation, slim) if hasattr(func, "__call__") else None

        # Bind class-level identity/config from decorator args (closure-safe)
        _FnServiceLLMService.origin = origin
        _FnServiceLLMService.bucket = bucket
        _FnServiceLLMService.name = name
        _FnServiceLLMService.codec_name = codec
        _FnServiceLLMService.prompt_plan = tuple(prompt_plan)
        _FnServiceLLMService.__name__ = f"{func.__name__}_Service"
        _FnServiceLLMService.__module__ = getattr(func, "__module__", __name__)
        return _FnServiceLLMService
    return wrap