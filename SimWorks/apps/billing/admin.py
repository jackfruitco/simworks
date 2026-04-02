import json

from django.contrib import admin
from django.utils import timezone

from apps.billing.forms import (
    EntitlementAdminForm,
    SeatAllocationAdminForm,
    SeatAssignmentAdminForm,
)
from apps.billing.models import (
    BillingAccount,
    Entitlement,
    SeatAllocation,
    SeatAssignment,
    Subscription,
    WebhookEvent,
)
from apps.billing.providers.apple import sync_apple_transaction_event
from apps.billing.providers.stripe import process_stripe_webhook


@admin.action(description="Replay selected webhook events")
def replay_webhook_events(modeladmin, request, queryset):
    for event in queryset:
        if event.provider_type == "stripe":
            process_stripe_webhook(
                payload_bytes=json.dumps(event.payload).encode("utf-8"),
                signature_header=(event.request_headers or {}).get("Stripe-Signature", ""),
            )
        elif event.provider_type == "apple":
            from apps.accounts.models import Account

            account_uuid = (event.payload or {}).get("account_uuid")
            account = Account.objects.filter(uuid=account_uuid).first()
            if account:
                sync_apple_transaction_event(account=account, payload=event.payload)


@admin.action(description="Grant comp access")
def grant_comp_access(modeladmin, request, queryset):
    for entitlement in queryset:
        entitlement.status = Entitlement.Status.ACTIVE
        entitlement.ends_at = None
        entitlement.metadata["comped_by_admin"] = True
        entitlement.metadata["comped_at"] = timezone.now().isoformat()
        entitlement.save(update_fields=["status", "ends_at", "metadata"])


@admin.action(description="Revoke selected entitlements")
def revoke_entitlements(modeladmin, request, queryset):
    for entitlement in queryset:
        entitlement.status = Entitlement.Status.REVOKED
        entitlement.ends_at = timezone.now()
        entitlement.save(update_fields=["status", "ends_at"])


@admin.register(BillingAccount)
class BillingAccountAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "provider_type",
        "provider_customer_id",
        "billing_email",
        "is_active",
    )
    list_filter = ("provider_type", "is_active")
    search_fields = ("account__name", "provider_customer_id", "billing_email")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("account", "provider_type", "plan_code", "status", "current_period_end")
    list_filter = ("provider_type", "status", "plan_code")
    search_fields = (
        "account__name",
        "provider_subscription_id",
        "provider_original_transaction_id",
    )


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    form = EntitlementAdminForm
    list_display = (
        "account",
        "product_code",
        "feature_code",
        "limit_code",
        "status",
        "subject_user",
    )
    list_filter = ("status", "product_code", "scope_type", "source_type")
    search_fields = ("account__name", "source_ref", "subject_user__email")
    actions = (grant_comp_access, revoke_entitlements)
    fields = (
        "account",
        "source_type",
        "source_ref",
        "scope_type",
        "subject_user",
        "product_code",
        "status",
        "portable_across_accounts",
        "starts_at",
        "ends_at",
        "metadata",
    )


@admin.register(SeatAllocation)
class SeatAllocationAdmin(admin.ModelAdmin):
    form = SeatAllocationAdminForm
    list_display = (
        "account",
        "product_code",
        "seat_limit",
        "seat_used",
        "effective_from",
        "effective_to",
    )
    list_filter = ("product_code",)


@admin.register(SeatAssignment)
class SeatAssignmentAdmin(admin.ModelAdmin):
    form = SeatAssignmentAdminForm
    list_display = ("account", "user", "product_code", "assigned_by", "assigned_at", "ended_at")
    list_filter = ("product_code",)
    search_fields = ("account__name", "user__email")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "provider_type",
        "event_id",
        "event_type",
        "status",
        "received_at",
        "processed_at",
    )
    list_filter = ("provider_type", "status", "event_type")
    search_fields = ("event_id", "event_type")
    actions = (replay_webhook_events,)
