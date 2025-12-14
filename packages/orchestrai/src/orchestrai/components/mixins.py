# orchestrai/components/mixins.py
from inspect import iscoroutinefunction

from asgiref.sync import async_to_sync
from asgiref.sync import sync_to_async

from ..tracing import service_span, SpanPath


class SetupTeardownMixin:
    """
    Mixin for components that may need setup/teardown.
    Sync methods are no-op by default; async variants
    delegate to sync when present.
    """

    def setup(self, **ctx):
        return self

    def teardown(self, **ctx):
        return self

    async def asetup(self, **ctx):
        maybe = getattr(self, "setup", None)
        if callable(maybe):
            if iscoroutinefunction(maybe):
                await maybe(**ctx)
            else:
                await sync_to_async(maybe)(**ctx)
        return self

    async def ateardown(self, **ctx):
        maybe = getattr(self, "teardown", None)
        if callable(maybe):
            if iscoroutinefunction(maybe):
                await maybe(**ctx)
            else:
                await sync_to_async(maybe)(**ctx)
        return self


class LifecycleMixin(SetupTeardownMixin):
    """
    Async-first execution lifecycle:

        asetup -> arun -> ateardown -> afinalize

    Exposes:
        - aexecute(**ctx): async orchestration
        - execute(**ctx): sync wrapper around `aexecute(**ctx)`
    """

    async def arun(self, **ctx):
        """Override this method to implement the actual service logic."""
        raise NotImplementedError

    def finalize(self, result, **ctx):
        """Override this to post-process the result."""
        return result

    async def afinalize(self, result, **ctx):
        """Async wrapper for `finalize`."""
        maybe = getattr(self, "finalize", None)
        if callable(maybe):
            if iscoroutinefunction(maybe):
                return await maybe(result, **ctx)
            else:
                return await sync_to_async(maybe)(result, **ctx)
        return result

    async def aexecute(self, **ctx):
        """Full lifecycle execution with tracing spans for each phase."""
        # Best-effort context flattening for span attributes
        attrs = {}
        maybe_flatten = getattr(self, "flatten_context", None)
        if callable(maybe_flatten):
            try:
                attrs = maybe_flatten()
            except Exception:
                attrs = {}

        span_root = SpanPath(("simcore", "svc", self.__class__.__name__))

        async with service_span(span_root.child("execute"), attributes=attrs):
            async with service_span(span_root.child("execute", "setup"), attributes=attrs):
                await self.asetup(**ctx)
            try:
                async with service_span(span_root.child("execute", "run"), attributes=attrs):
                    if hasattr(self, "arun") and iscoroutinefunction(self.arun):
                        result = await self.arun(**ctx)
                    else:
                        result = await sync_to_async(self.run)(**ctx)
            finally:
                async with service_span(span_root.child("execute", "teardown"), attributes=attrs):
                    await self.ateardown(**ctx)
            async with service_span(span_root.child("execute", "finalize"), attributes=attrs):
                return await self.afinalize(result, **ctx)

    def execute(self, **ctx):
        """Sync wrapper around `aexecute`."""
        return async_to_sync(self.aexecute)(**ctx)
