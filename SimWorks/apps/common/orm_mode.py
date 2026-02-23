"""Django project helpers for enforcing ORM execution mode."""

from orchestrai.orm_mode import must_be_async, must_be_sync

__all__ = ["must_be_async", "must_be_sync"]
