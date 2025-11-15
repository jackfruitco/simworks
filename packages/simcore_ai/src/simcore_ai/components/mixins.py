# simcore_ai/components/mixins.py


from asgiref.sync import async_to_sync


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
            maybe(**ctx)
        return self

    async def ateardown(self, **ctx):
        maybe = getattr(self, "teardown", None)
        if callable(maybe):
            maybe(**ctx)
        return self


class LifecycleMixin(SetupTeardownMixin):
    """
    Async-first execution lifecycle:

        asetup -> arun -> ateardown -> Afinalize

    Exposes:
        - arun_all(**ctx): async orchestration
        - run_all(**ctx): sync wrapper around `arun_all(**ctx)`
    """

    async def arun(self, **ctx):
        """Override this method to implement the actual service logic."""
        raise NotImplementedError

    async def afinalize(self, result, **ctx):
        """Override this method to post-process the result."""
        return result

    async def arun_all(self, **ctx):
        """Full lifecycle execution."""
        await self.asetup(**ctx)
        try:
            result = await self.arun(**ctx)
        finally:
            await self.ateardown(**ctx)
        return await self.afinalize(result, **ctx)

    def run_all(self, **ctx):
        """Sync wrapper around `arun`."""
        return async_to_sync(self.arun_all)(**ctx)