# trainerlab/orca/mixins.py
"""Base mixin for TrainerLab instruction-scoped identities."""

from orchestrai_django.identity import DjangoIdentityMixin


class TrainerlabNamespaceMixin(DjangoIdentityMixin):
    """Identity mixin for the TrainerLab app namespace."""

    namespace = "trainerlab"
