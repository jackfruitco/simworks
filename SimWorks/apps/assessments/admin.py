"""Admin registrations for the assessments app.

Published rubrics are rendered read-only to enforce immutability at the
admin layer. Future staff/enterprise customization will happen via DB/UI
(e.g. cloning a draft from a published rubric); the admin intentionally
does not expose direct field edits on a published rubric.
"""

from __future__ import annotations

from django.contrib import admin

from .models import (
    Assessment,
    AssessmentCriterion,
    AssessmentCriterionScore,
    AssessmentRubric,
    AssessmentSource,
)


class AssessmentCriterionInline(admin.TabularInline):
    model = AssessmentCriterion
    extra = 0
    fields = (
        "slug",
        "label",
        "category",
        "value_type",
        "min_value",
        "max_value",
        "weight",
        "sort_order",
        "required",
        "include_in_user_summary",
    )
    show_change_link = True


@admin.register(AssessmentRubric)
class AssessmentRubricAdmin(admin.ModelAdmin):
    list_display = (
        "slug",
        "name",
        "version",
        "scope",
        "lab_type",
        "assessment_type",
        "status",
        "published_at",
        "account",
    )
    list_filter = ("status", "scope", "lab_type", "assessment_type")
    search_fields = ("slug", "name", "description")
    readonly_fields = (
        "created_at",
        "updated_at",
        "published_at",
        "seed_source_app",
        "seed_source_path",
        "seed_checksum",
    )
    inlines = (AssessmentCriterionInline,)
    ordering = ("slug", "-version")

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status == AssessmentRubric.Status.PUBLISHED:
            for field in obj._PUBLISHED_LOCKED_FIELDS:
                # Strip the FK '_id' suffix used internally for the lock list.
                attr = field[:-3] if field.endswith("_id") else field
                if attr not in readonly:
                    readonly.append(attr)
        return readonly


@admin.register(AssessmentCriterion)
class AssessmentCriterionAdmin(admin.ModelAdmin):
    list_display = (
        "rubric",
        "slug",
        "label",
        "category",
        "value_type",
        "weight",
        "sort_order",
        "required",
    )
    list_filter = ("value_type", "category", "required")
    search_fields = ("slug", "label", "rubric__slug")
    ordering = ("rubric", "sort_order")
    readonly_fields = ("created_at", "updated_at")


class AssessmentCriterionScoreInline(admin.TabularInline):
    model = AssessmentCriterionScore
    extra = 0
    fields = (
        "criterion",
        "value_bool",
        "value_int",
        "value_decimal",
        "value_text",
        "value_json",
        "score",
    )
    readonly_fields = (
        "criterion",
        "value_bool",
        "value_int",
        "value_decimal",
        "value_text",
        "value_json",
        "score",
    )
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class AssessmentSourceInline(admin.TabularInline):
    model = AssessmentSource
    fk_name = "assessment"
    extra = 0
    fields = ("source_type", "role", "simulation", "source_assessment", "created_at")
    readonly_fields = (
        "source_type",
        "role",
        "simulation",
        "source_assessment",
        "created_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "assessment_type",
        "lab_type",
        "rubric",
        "assessed_user",
        "account",
        "overall_score",
        "created_at",
    )
    list_filter = ("assessment_type", "lab_type")
    search_fields = (
        "id",
        "assessed_user__email",
        "rubric__slug",
        "overall_summary",
    )
    readonly_fields = ("id", "created_at", "updated_at", "source_attempt")
    inlines = (AssessmentCriterionScoreInline, AssessmentSourceInline)
    ordering = ("-created_at",)


@admin.register(AssessmentCriterionScore)
class AssessmentCriterionScoreAdmin(admin.ModelAdmin):
    list_display = (
        "assessment",
        "criterion",
        "score",
        "value_bool",
        "value_int",
        "value_decimal",
    )
    list_filter = ("criterion__value_type",)
    search_fields = ("assessment__id", "criterion__slug")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AssessmentSource)
class AssessmentSourceAdmin(admin.ModelAdmin):
    list_display = (
        "assessment",
        "source_type",
        "role",
        "simulation",
        "source_assessment",
        "created_at",
    )
    list_filter = ("source_type", "role")
    search_fields = (
        "assessment__id",
        "simulation__id",
        "source_assessment__id",
    )
    readonly_fields = ("created_at",)
