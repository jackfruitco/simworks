# chatlab/orca/mixins/stitch.py
"""Identity mixin for Stitch AI facilitator services and schemas."""

from orchestrai_django.identity import DjangoIdentityMixin


class StitchMixin(DjangoIdentityMixin):
    """Identity mixin for the stitch group within the chatlab namespace."""
    group = "stitch"
