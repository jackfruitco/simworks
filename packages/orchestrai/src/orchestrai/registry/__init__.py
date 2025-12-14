"""Registry package."""

# Intentionally avoid importing heavy dependencies here to keep ``orchestrai``
# import light. The Celery-like app uses ``registry.simple.Registry``; the
# legacy registries remain available by importing their modules directly.

__all__: tuple[str, ...] = ()