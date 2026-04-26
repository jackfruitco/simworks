"""Public service surface for the assessments app.

Importable shortcuts so callers can write::

    from apps.assessments.services import resolve_rubric

without reaching into submodules.
"""

from .rubric_resolution import RubricNotFoundError, resolve_rubric
from .scoring import compute_overall_score, normalize_criterion_value

__all__ = [
    "RubricNotFoundError",
    "compute_overall_score",
    "normalize_criterion_value",
    "resolve_rubric",
]
