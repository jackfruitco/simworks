from typing import Sequence, Callable
from .base import LLMServiceBase
from .identity import ServiceIdentity


def llm_service(*, origin: str, bucket: str, name: str, codec: str, prompt_plan: Sequence[tuple[str, str]]):
    """
    Decorate a simple async function and expose it as an LLMServiceBase subclass.
    The returned class inherits retry/telemetry behavior from LLMServiceBase.
    - origin: producer/project ('simcore', 'trainerlab', ...)
    - bucket: functional group ('feedback', 'triage', ...)
    - name:   concrete operation ('generate-initial', ...)
    """
    def wrap(func: Callable):
        class _FnService(LLMServiceBase):
            async def on_success(self, simulation, slim):
                if func.__code__.co_argcount >= 2:
                    return await func(simulation, slim) if hasattr(func, "__call__") else None

        # Bind class-level identity/config from decorator args (closure-safe)
        _FnService.origin = origin
        _FnService.bucket = bucket
        _FnService.name = name
        _FnService.codec_name = codec
        _FnService.prompt_plan = tuple(prompt_plan)
        _FnService.__name__ = f"{func.__name__}_Service"
        _FnService.__module__ = getattr(func, "__module__", __name__)
        return _FnService
    return wrap