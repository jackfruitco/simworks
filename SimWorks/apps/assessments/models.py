"""Models for the assessments app.

This module defines a rubric-backed assessment system that replaces the
legacy ``SimulationFeedback`` polymorphic-metadata storage.

Key concepts:

- :class:`AssessmentRubric` — a versioned, scope-aware rubric (global or
  account-scoped). Published rubrics are immutable.
- :class:`AssessmentCriterion` — one assessable item belonging to a rubric;
  its ``value_type`` controls which ``value_*`` field on a score is populated.
- :class:`Assessment` — a completed assessment (one row per
  rubric-evaluation event). Carries the typed normalized
  ``overall_score`` and the narrative ``overall_summary``.
- :class:`AssessmentCriterionScore` — per-criterion result with typed
  ``value_*`` fields plus a normalized 0..1 ``score``, optional rationale,
  and a structured ``evidence`` list.
- :class:`AssessmentSource` — declares where an assessment came from. An
  assessment may have multiple sources (e.g. one primary simulation plus
  a ``generated_from`` parent assessment for continuation Q&A).
"""

from __future__ import annotations

from decimal import Decimal
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone


class AssessmentRubric(models.Model):
    """A versioned rubric defining the criteria for an assessment.

    Rubrics may be ``global`` (account is null) or ``account``-scoped
    (account is set). Published rubrics are immutable except for the
    ``status`` transition draft → published → archived.
    """

    class Scope(models.TextChoices):
        GLOBAL = "global", "Global"
        ACCOUNT = "account", "Account"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    # Field names on this class that may not be mutated once status=PUBLISHED.
    # ``status`` itself is intentionally excluded so PUBLISHED → ARCHIVED is allowed.
    _PUBLISHED_LOCKED_FIELDS = (
        "slug",
        "name",
        "description",
        "lab_type",
        "assessment_type",
        "version",
        "scope",
        "account_id",
        "based_on_id",
        "seed_source_app",
        "seed_source_path",
        "seed_checksum",
        "published_at",
    )

    slug = models.SlugField(max_length=120)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.GLOBAL)
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="assessment_rubrics",
    )

    lab_type = models.CharField(max_length=40, blank=True, db_index=True)
    assessment_type = models.CharField(max_length=60, db_index=True)

    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    based_on = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derivatives",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rubrics_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rubrics_updated",
    )

    seed_source_app = models.CharField(max_length=80, blank=True, default="")
    seed_source_path = models.CharField(max_length=255, blank=True, default="")
    seed_checksum = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "version"],
                condition=models.Q(account__isnull=True),
                name="uniq_rubric_global_slug_version",
            ),
            models.UniqueConstraint(
                fields=["account", "slug", "version"],
                condition=models.Q(account__isnull=False),
                name="uniq_rubric_account_slug_version",
            ),
            models.CheckConstraint(
                name="rubric_account_matches_scope",
                condition=(
                    (models.Q(scope="account") & models.Q(account__isnull=False))
                    | (models.Q(scope="global") & models.Q(account__isnull=True))
                ),
            ),
        ]
        indexes = [
            models.Index(
                fields=["lab_type", "assessment_type", "status"],
                name="rubric_lab_type_status_idx",
            ),
            models.Index(fields=["account", "status"], name="rubric_account_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.slug} v{self.version} ({self.status})"

    def clean(self) -> None:
        super().clean()
        if self.scope == self.Scope.ACCOUNT and self.account_id is None:
            raise ValidationError({"account": "Account-scoped rubric requires an account."})
        if self.scope == self.Scope.GLOBAL and self.account_id is not None:
            raise ValidationError({"account": "Global rubric must not set an account."})

    def save(self, *args, **kwargs):
        if self.pk:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .only("status", *self._PUBLISHED_LOCKED_FIELDS)
                .first()
            )
            if previous is not None and previous.status == self.Status.PUBLISHED:
                # PUBLISHED → DRAFT is forbidden; PUBLISHED → ARCHIVED is allowed.
                if self.status == self.Status.DRAFT:
                    raise ValidationError("Cannot revert a published rubric to draft.")
                for field in self._PUBLISHED_LOCKED_FIELDS:
                    if getattr(previous, field) != getattr(self, field):
                        raise ValidationError(f"Cannot modify {field!r} on a published rubric.")

        # On first transition to PUBLISHED, stamp published_at.
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()

        self.full_clean()
        return super().save(*args, **kwargs)


class AssessmentCriterion(models.Model):
    """One assessable item belonging to a rubric.

    The ``value_type`` controls which value_* field on
    :class:`AssessmentCriterionScore` must be populated when a score is
    recorded for this criterion.
    """

    class ValueType(models.TextChoices):
        BOOL = "bool", "Boolean"
        INT = "int", "Integer"
        DECIMAL = "decimal", "Decimal"
        TEXT = "text", "Text"
        ENUM = "enum", "Enum"
        JSON = "json", "JSON"

    rubric = models.ForeignKey(AssessmentRubric, on_delete=models.CASCADE, related_name="criteria")
    slug = models.SlugField(max_length=80)
    label = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=60, blank=True, default="")

    value_type = models.CharField(max_length=10, choices=ValueType.choices)

    min_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    allowed_values = models.JSONField(default=list, blank=True)

    weight = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("1.000"))
    sort_order = models.PositiveIntegerField(default=0)
    required = models.BooleanField(default=True)
    include_in_user_summary = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["rubric", "slug"], name="uniq_criterion_rubric_slug"),
            models.CheckConstraint(
                condition=models.Q(weight__gte=0), name="criterion_weight_nonnegative"
            ),
        ]
        ordering = ["rubric_id", "sort_order"]

    def __str__(self) -> str:
        return f"{self.rubric.slug}/{self.slug} ({self.value_type})"

    def _protect_delete_when_rubric_published(self) -> None:
        if not self.rubric_id:
            return
        rubric_status = AssessmentRubric.objects.only("status").get(pk=self.rubric_id).status
        if rubric_status == AssessmentRubric.Status.PUBLISHED:
            raise ValidationError("Cannot delete criteria of a published rubric.")

    def clean(self) -> None:
        super().clean()
        if self.value_type == self.ValueType.ENUM:
            if not self.allowed_values:
                raise ValidationError(
                    {"allowed_values": "Enum criterion requires non-empty allowed_values."}
                )
        else:
            if self.allowed_values:
                raise ValidationError(
                    {"allowed_values": ("allowed_values may only be set for enum criteria.")}
                )

        numeric_types = {self.ValueType.INT, self.ValueType.DECIMAL}
        if self.value_type not in numeric_types:
            if self.min_value is not None or self.max_value is not None:
                raise ValidationError(
                    "min_value / max_value may only be set on int or decimal criteria."
                )
        else:
            if (
                self.min_value is not None
                and self.max_value is not None
                and self.min_value > self.max_value
            ):
                raise ValidationError("min_value must be <= max_value.")

    def save(self, *args, **kwargs):
        if self.rubric_id:
            rubric_status = AssessmentRubric.objects.only("status").get(pk=self.rubric_id).status
            if rubric_status == AssessmentRubric.Status.PUBLISHED:
                raise ValidationError("Cannot create or modify criteria of a published rubric.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._protect_delete_when_rubric_published()
        return super().delete(*args, **kwargs)


class Assessment(models.Model):
    """A completed assessment record.

    An Assessment is bound to exactly one rubric (PROTECT) and one account,
    and may be linked to one or more sources (simulations, parent
    assessments) via :class:`AssessmentSource`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    rubric = models.ForeignKey(
        AssessmentRubric, on_delete=models.PROTECT, related_name="assessments"
    )
    account = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="assessments"
    )
    assessed_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assessments_received",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessments_authored",
    )

    assessment_type = models.CharField(max_length=60, db_index=True)
    lab_type = models.CharField(max_length=40, blank=True, db_index=True)

    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)

    overall_summary = models.TextField(blank=True, default="")
    overall_score = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)

    generated_by_service = models.CharField(max_length=120, blank=True, default="")
    source_attempt = models.ForeignKey(
        "orchestrai_django.ServiceCallAttempt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="assessment_overall_score_in_unit",
                condition=(
                    models.Q(overall_score__isnull=True)
                    | (models.Q(overall_score__gte=0) & models.Q(overall_score__lte=1))
                ),
            ),
        ]
        indexes = [
            models.Index(
                fields=["account", "lab_type", "assessment_type"],
                name="assessment_acct_lab_type_idx",
            ),
            models.Index(
                fields=["assessed_user", "lab_type"],
                name="assessment_user_lab_idx",
            ),
            models.Index(fields=["rubric"], name="assessment_rubric_idx"),
        ]

    def __str__(self) -> str:
        return f"Assessment {self.id} ({self.assessment_type})"


class AssessmentCriterionScore(models.Model):
    """Typed result for a single criterion within an assessment.

    Exactly one ``value_*`` field is populated per row, matching the
    parent criterion's ``value_type``. ``score`` is the normalized 0..1
    value (may be null for free-text or json criteria).

    ``evidence`` shape (documented for clarity; not validated beyond
    "must be a JSON list")::

        [
            {
                "type": "message",
                "message_id": 123,
                "quote": "I think it's reflux.",
                "reason": "Missed possible cardiac red flag.",
            }
        ]
    """

    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="criterion_scores"
    )
    criterion = models.ForeignKey(
        AssessmentCriterion, on_delete=models.PROTECT, related_name="scores"
    )

    value_bool = models.BooleanField(null=True, blank=True)
    value_int = models.IntegerField(null=True, blank=True)
    value_decimal = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    value_text = models.TextField(blank=True, default="")
    value_json = models.JSONField(null=True, blank=True)

    score = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    rationale = models.TextField(blank=True, default="")
    evidence = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Structured evidence list. Expected entries: "
            '{"type": "message", "message_id": int, '
            '"quote": str, "reason": str}.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "criterion"],
                name="uniq_score_assessment_criterion",
            ),
            models.CheckConstraint(
                name="score_in_unit",
                condition=(
                    models.Q(score__isnull=True) | (models.Q(score__gte=0) & models.Q(score__lte=1))
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"Score({self.criterion.slug}) for assessment={self.assessment_id}"

    def clean(self) -> None:
        super().clean()

        # 1. Criterion must belong to the assessment's rubric.
        if self.criterion.rubric_id != self.assessment.rubric_id:
            raise ValidationError("criterion does not belong to the assessment's rubric.")

        # 2. Exactly the right value field set for the criterion's value_type.
        vt = self.criterion.value_type
        VT = AssessmentCriterion.ValueType
        text_provided = bool(self.value_text)

        populated_fields = {
            "value_bool": self.value_bool is not None,
            "value_int": self.value_int is not None,
            "value_decimal": self.value_decimal is not None,
            "value_text": text_provided,
            "value_json": self.value_json is not None,
        }

        expected_field_by_type = {
            VT.BOOL: "value_bool",
            VT.INT: "value_int",
            VT.DECIMAL: "value_decimal",
            VT.TEXT: "value_text",
            VT.ENUM: "value_text",
            VT.JSON: "value_json",
        }
        expected = expected_field_by_type[vt]
        if not populated_fields[expected]:
            raise ValidationError(f"value_type={vt!r} requires {expected} to be populated.")
        for name, populated in populated_fields.items():
            if name != expected and populated:
                raise ValidationError(f"value_type={vt!r} must not populate {name}.")

        # 3. Numeric range checks.
        if vt == VT.INT and self.value_int is not None:
            if (
                self.criterion.min_value is not None
                and Decimal(self.value_int) < self.criterion.min_value
            ):
                raise ValidationError(
                    {"value_int": f"Below criterion min_value ({self.criterion.min_value})."}
                )
            if (
                self.criterion.max_value is not None
                and Decimal(self.value_int) > self.criterion.max_value
            ):
                raise ValidationError(
                    {"value_int": f"Above criterion max_value ({self.criterion.max_value})."}
                )
        if vt == VT.DECIMAL and self.value_decimal is not None:
            if (
                self.criterion.min_value is not None
                and self.value_decimal < self.criterion.min_value
            ):
                raise ValidationError(
                    {"value_decimal": f"Below criterion min_value ({self.criterion.min_value})."}
                )
            if (
                self.criterion.max_value is not None
                and self.value_decimal > self.criterion.max_value
            ):
                raise ValidationError(
                    {"value_decimal": f"Above criterion max_value ({self.criterion.max_value})."}
                )

        # 4. Enum allowed_values check.
        if vt == VT.ENUM:
            allowed = self.criterion.allowed_values or []
            if self.value_text not in allowed:
                raise ValidationError(
                    {"value_text": f"value_text {self.value_text!r} not in allowed_values."}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AssessmentSource(models.Model):
    """Declares a source from which an assessment was generated.

    An assessment may have multiple sources (e.g. one ``primary`` simulation
    plus a ``generated_from`` parent assessment for continuation Q&A).
    Either ``simulation`` or ``source_assessment`` is set, never both,
    determined by ``source_type``. Source references are protected on delete
    so provenance rows cannot silently become nullable tombstones.
    """

    class SourceType(models.TextChoices):
        SIMULATION = "simulation", "Simulation"
        ASSESSMENT = "assessment", "Assessment"

    class Role(models.TextChoices):
        PRIMARY = "primary", "Primary"
        CONTRIBUTING = "contributing", "Contributing"
        GENERATED_FROM = "generated_from", "Generated From"
        EVIDENCE = "evidence", "Evidence"

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="sources")

    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PRIMARY)

    simulation = models.ForeignKey(
        "simcore.Simulation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_sources",
    )
    source_assessment = models.ForeignKey(
        "assessments.Assessment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="referenced_by_sources",
    )

    notes = models.TextField(blank=True, default="")
    snapshot = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "role"],
                condition=models.Q(role="primary"),
                name="uniq_primary_source_per_assessment",
            ),
        ]
        indexes = [
            models.Index(fields=["assessment", "role"], name="src_assessment_role_idx"),
            models.Index(fields=["simulation"], name="src_simulation_idx"),
            models.Index(fields=["source_assessment"], name="src_source_assessment_idx"),
        ]

    def __str__(self) -> str:
        return f"Source({self.source_type}/{self.role}) for {self.assessment_id}"

    def clean(self) -> None:
        super().clean()
        if self.source_type == self.SourceType.SIMULATION:
            if self.simulation_id is None:
                raise ValidationError(
                    {"simulation": "simulation is required when source_type=simulation."}
                )
            if self.source_assessment_id is not None:
                raise ValidationError(
                    {
                        "source_assessment": (
                            "source_assessment must be null when source_type=simulation."
                        )
                    }
                )
        elif self.source_type == self.SourceType.ASSESSMENT:
            if self.source_assessment_id is None:
                raise ValidationError(
                    {
                        "source_assessment": (
                            "source_assessment is required when source_type=assessment."
                        )
                    }
                )
            if self.simulation_id is not None:
                raise ValidationError(
                    {"simulation": "simulation must be null when source_type=assessment."}
                )
            if self.source_assessment_id == self.assessment_id:
                raise ValidationError("source_assessment cannot equal assessment.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


@receiver(pre_delete, sender=AssessmentCriterion)
def _protect_published_rubric_criterion_delete(sender, instance, **kwargs):
    instance._protect_delete_when_rubric_published()
