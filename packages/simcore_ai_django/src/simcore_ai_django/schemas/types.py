# simcore_ai_django/schemas/types.py
from simcore_ai.types.base import StrictBaseModel
from simcore_ai_django.identity import DjangoIdentityMixin


class DjangoStrictSchema(DjangoIdentityMixin, StrictBaseModel):
    """Django-aware schema base: auto-derive (origin, bucket, name) from app label."""
    pass
