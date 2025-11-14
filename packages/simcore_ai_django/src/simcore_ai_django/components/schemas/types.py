# simcore_ai_django/schemas/types.py
from simcore_ai.components import BaseOutputSchema
from simcore_ai.components.schemas.base import BaseOutputItem
from simcore_ai_django.identity.mixins import DjangoIdentityMixin

__all__ = [
    "DjangoBaseOutputSchema",
    "DjangoBaseOutputBlock",
    "DjangoBaseOutputItem",
]


class DjangoBaseOutputSchema(DjangoIdentityMixin, BaseOutputSchema):
    """Django-aware schema base: auto-derive (namespace, kind, name) from app label."""
    __identity_abstract__ = True


class DjangoBaseOutputBlock(BaseOutputSchema):
    """Re-export of BaseOutputSchema for Django-facing code paths (no identity)."""
    __identity_abstract__ = True


class DjangoBaseOutputItem(BaseOutputItem):
    """Re-export of BaseOutputItem for Django-facing code paths (no identity)."""
    __identity_abstract__ = True
