from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import PersistModel


class UserFeedback(PersistModel):
    """User-submitted product/app/simulation feedback.

    Separate from AI-generated or trainer-generated evaluation feedback (hotwash).
    Covers general app feedback and simulation-scoped feedback across all labs.
    """

    class Category(models.TextChoices):
        BUG_REPORT = "bug_report", "Bug Report"
        UX_ISSUE = "ux_issue", "UX Issue"
        SIMULATION_CONTENT = "simulation_content", "Simulation Content"
        FEATURE_REQUEST = "feature_request", "Feature Request"
        OTHER = "other", "Other"

    class Source(models.TextChoices):
        IN_APP = "in_app", "In App"
        TESTFLIGHT = "testflight", "TestFlight"
        ADMIN = "admin", "Admin"
        API = "api", "API"
        UNKNOWN = "unknown", "Unknown"

    class Status(models.TextChoices):
        NEW = "new", "New"
        TRIAGED = "triaged", "Triaged"
        PLANNED = "planned", "Planned"
        RESOLVED = "resolved", "Resolved"
        WONT_FIX = "wont_fix", "Won't Fix"
        DUPLICATE = "duplicate", "Duplicate"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class ClientPlatform(models.TextChoices):
        IOS = "ios", "iOS"
        WEB = "web", "Web"
        ANDROID = "android", "Android"
        UNKNOWN = "unknown", "Unknown"

    # ── Timestamps ────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── Ownership / linkage ───────────────────────────────────────────
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_submissions",
    )
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_submissions",
    )
    simulation = models.ForeignKey(
        "simcore.Simulation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_feedback",
    )
    conversation = models.ForeignKey(
        "simcore.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_feedback",
    )

    # ── Classification ────────────────────────────────────────────────
    lab_type = models.CharField(max_length=32, blank=True, default="")
    category = models.CharField(max_length=32, choices=Category.choices, db_index=True)
    source = models.CharField(
        max_length=32,
        choices=Source.choices,
        default=Source.IN_APP,
        db_index=True,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    severity = models.CharField(max_length=32, choices=Severity.choices, blank=True, default="")

    # ── Content ───────────────────────────────────────────────────────
    title = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField()
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    email = models.EmailField(blank=True, default="")
    allow_follow_up = models.BooleanField(default=True)

    # ── Client / request metadata ─────────────────────────────────────
    client_platform = models.CharField(
        max_length=32,
        choices=ClientPlatform.choices,
        default=ClientPlatform.UNKNOWN,
    )
    client_version = models.CharField(max_length=100, blank=True, default="")
    os_version = models.CharField(max_length=100, blank=True, default="")
    device_model = models.CharField(max_length=100, blank=True, default="")
    request_id = models.CharField(max_length=255, blank=True, default="")
    session_identifier = models.CharField(max_length=255, blank=True, default="")
    context_json = models.JSONField(default=dict, blank=True)
    attachments_json = models.JSONField(default=list, blank=True)

    # ── Staff-only fields ─────────────────────────────────────────────
    internal_notes = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_feedback",
    )

    class Meta:
        verbose_name = "User Feedback"
        verbose_name_plural = "User Feedback"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        user_label = self.user.email if self.user_id else "anonymous"
        snippet = self.title or self.body[:40]
        return f"[{self.category}] {snippet!r} by {user_label}"
