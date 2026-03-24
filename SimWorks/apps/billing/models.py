from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.models import Account
from apps.billing.catalog import is_valid_product_code


class ProviderType(models.TextChoices):
    STRIPE = "stripe", "Stripe"
    APPLE = "apple", "Apple"
    MANUAL = "manual", "Manual"
    INTERNAL = "internal", "Internal"


class BillingAccount(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="billing_accounts",
    )
    provider_type = models.CharField(max_length=20, choices=ProviderType.choices)
    provider_customer_id = models.CharField(max_length=255, blank=True, default="")
    tax_exempt_status = models.CharField(max_length=50, blank=True, default="")
    billing_email = models.EmailField(blank=True, default="")
    country_code = models.CharField(max_length=2, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("account_id", "provider_type", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["provider_type", "provider_customer_id"],
                condition=Q(provider_customer_id__gt=""),
                name="uniq_billing_account_provider_customer",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "provider_type"], name="idx_billing_account_provider"),
            models.Index(fields=["billing_email"], name="idx_billing_account_email"),
        ]

    def __str__(self):
        return f"{self.account_id}:{self.provider_type}"


class Subscription(models.Model):
    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        GRACE_PERIOD = "grace_period", "Grace Period"
        PAST_DUE = "past_due", "Past Due"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"
        PAUSED = "paused", "Paused"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    billing_account = models.ForeignKey(
        "billing.BillingAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions",
    )
    provider_type = models.CharField(max_length=20, choices=ProviderType.choices)
    provider_subscription_id = models.CharField(max_length=255, blank=True, default="")
    provider_original_transaction_id = models.CharField(max_length=255, blank=True, default="")
    plan_code = models.CharField(max_length=100)
    status = models.CharField(max_length=32, choices=Status.choices)
    starts_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    ended_at = models.DateTimeField(null=True, blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("account_id", "-updated_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=["provider_type", "provider_subscription_id"],
                condition=Q(provider_subscription_id__gt=""),
                name="uniq_subscription_provider_id",
            ),
            models.UniqueConstraint(
                fields=["provider_type", "provider_original_transaction_id"],
                condition=Q(provider_original_transaction_id__gt=""),
                name="uniq_subscription_original_txn",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "status"], name="idx_subscription_account_status"),
            models.Index(fields=["plan_code", "status"], name="idx_subscription_plan_status"),
        ]

    def __str__(self):
        provider_ref = (
            self.provider_subscription_id or self.provider_original_transaction_id or "n/a"
        )
        return f"{self.account_id}:{self.provider_type}:{provider_ref}"


class Entitlement(models.Model):
    class SourceType(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        MEMBERSHIP = "membership", "Membership"
        GRANT = "grant", "Grant"
        MANUAL = "manual", "Manual"
        PROMO = "promo", "Promo"

    class ScopeType(models.TextChoices):
        ACCOUNT = "account", "Account"
        USER = "user", "User"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SCHEDULED = "scheduled", "Scheduled"
        EXPIRED = "expired", "Expired"
        REVOKED = "revoked", "Revoked"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="entitlements",
    )
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    source_ref = models.CharField(max_length=255)
    scope_type = models.CharField(max_length=20, choices=ScopeType.choices)
    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entitlements",
    )
    product_code = models.CharField(max_length=100)
    feature_code = models.CharField(max_length=100, blank=True, default="")
    limit_code = models.CharField(max_length=100, blank=True, default="")
    limit_value = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    portable_across_accounts = models.BooleanField(default=False)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("account_id", "product_code", "feature_code", "limit_code", "id")
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "account",
                    "source_type",
                    "source_ref",
                    "scope_type",
                    "product_code",
                    "feature_code",
                    "limit_code",
                ],
                condition=Q(subject_user__isnull=True),
                name="uniq_entitlement_source_account_scope_code",
            ),
            models.UniqueConstraint(
                fields=[
                    "account",
                    "source_type",
                    "source_ref",
                    "scope_type",
                    "subject_user",
                    "product_code",
                    "feature_code",
                    "limit_code",
                ],
                condition=Q(subject_user__isnull=False),
                name="uniq_entitlement_source_user_scope_code",
            ),
        ]
        indexes = [
            models.Index(
                fields=["account", "status", "product_code"], name="idx_entitlement_product"
            ),
            models.Index(
                fields=["subject_user", "status", "product_code"],
                name="idx_entitlement_user_product",
            ),
            models.Index(fields=["source_type", "source_ref"], name="idx_entitlement_source"),
        ]

    def __str__(self):
        target = self.subject_user_id or "account"
        return f"{self.account_id}:{target}:{self.product_code}:{self.feature_code or self.limit_code or 'access'}"

    def clean(self):
        super().clean()

        errors = {}
        if not is_valid_product_code(self.product_code):
            errors["product_code"] = "Enter a valid internal product code."

        if self.feature_code:
            errors["feature_code"] = "Feature grants are not supported in this billing pass."
        if self.limit_code:
            errors["limit_code"] = "Limit grants are not supported in this billing pass."
        if not self.limit_code and self.limit_value is not None:
            errors["limit_value"] = "Limit value must be empty when limit code is blank."
        if self.scope_type == self.ScopeType.USER and self.subject_user_id is None:
            errors["subject_user"] = "User-scoped entitlements require a subject user."
        if self.scope_type == self.ScopeType.ACCOUNT and self.subject_user_id is not None:
            errors["subject_user"] = "Account-scoped entitlements cannot target a subject user."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SeatAllocation(models.Model):
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="seat_allocations",
    )
    product_code = models.CharField(max_length=100)
    seat_limit = models.PositiveIntegerField()
    seat_used = models.PositiveIntegerField(default=0)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("account_id", "product_code", "-effective_from")
        indexes = [
            models.Index(fields=["account", "product_code"], name="idx_seat_allocation_product"),
        ]

    def __str__(self):
        return f"{self.account_id}:{self.product_code}:{self.seat_limit}"

    def clean(self):
        super().clean()
        if not is_valid_product_code(self.product_code):
            raise ValidationError({"product_code": "Enter a valid internal product code."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SeatAssignment(models.Model):
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="seat_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="seat_assignments",
    )
    product_code = models.CharField(max_length=100)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_seats",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("account_id", "product_code", "-assigned_at")
        constraints = [
            models.UniqueConstraint(
                fields=["account", "user", "product_code"],
                condition=Q(user__isnull=False, ended_at__isnull=True),
                name="uniq_open_seat_assignment",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "product_code"], name="idx_seat_assignment_product"),
            models.Index(fields=["user", "product_code"], name="idx_seat_assignment_user"),
        ]

    def __str__(self):
        return f"{self.account_id}:{self.user_id}:{self.product_code}"

    def clean(self):
        super().clean()
        if not is_valid_product_code(self.product_code):
            raise ValidationError({"product_code": "Enter a valid internal product code."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class WebhookEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    provider_type = models.CharField(max_length=20, choices=ProviderType.choices)
    event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=255)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField(default=dict, blank=True)
    request_headers = models.JSONField(default=dict, blank=True)
    processing_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-received_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=["provider_type", "event_id"],
                name="uniq_webhook_event_provider_event",
            ),
        ]
        indexes = [
            models.Index(fields=["provider_type", "status"], name="idx_webhook_provider_status"),
            models.Index(fields=["event_type", "received_at"], name="idx_webhook_type_received"),
        ]

    def __str__(self):
        return f"{self.provider_type}:{self.event_id}:{self.status}"
