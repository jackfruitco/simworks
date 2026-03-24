from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.services import create_account_audit_event
from apps.billing.catalog import (
    product_code_from_apple_product_id,
    product_code_from_stripe_plan_code,
)
from apps.billing.models import (
    BillingAccount,
    Entitlement,
    ProviderType,
    Subscription,
    WebhookEvent,
)

ACTIVE_SUBSCRIPTION_STATUSES = {
    Subscription.Status.TRIALING,
    Subscription.Status.ACTIVE,
    Subscription.Status.GRACE_PERIOD,
    Subscription.Status.PAST_DUE,
    Subscription.Status.CANCELED,
}


def upsert_billing_account(
    *,
    account,
    provider_type: str,
    provider_customer_id: str = "",
    billing_email: str = "",
    country_code: str = "",
    metadata: dict | None = None,
):
    billing_account, _ = BillingAccount.objects.update_or_create(
        account=account,
        provider_type=provider_type,
        defaults={
            "provider_customer_id": provider_customer_id or "",
            "billing_email": billing_email or "",
            "country_code": country_code or "",
            "metadata": metadata or {},
            "is_active": True,
        },
    )
    return billing_account


def _subscription_scope(subscription):
    if subscription.account.is_personal and subscription.account.owner_user_id:
        return {
            "scope_type": Entitlement.ScopeType.USER,
            "subject_user_id": subscription.account.owner_user_id,
            "portable_across_accounts": True,
        }
    return {
        "scope_type": Entitlement.ScopeType.ACCOUNT,
        "subject_user_id": None,
        "portable_across_accounts": False,
    }


def _subscription_is_active(subscription) -> bool:
    if subscription.status not in ACTIVE_SUBSCRIPTION_STATUSES:
        return False
    return not (
        subscription.current_period_end and subscription.current_period_end < timezone.now()
    )


def _subscription_product_code(subscription: Subscription) -> str:
    if subscription.provider_type == ProviderType.STRIPE:
        return product_code_from_stripe_plan_code(subscription.plan_code)
    if subscription.provider_type == ProviderType.APPLE:
        return product_code_from_apple_product_id(subscription.plan_code)
    return ""


@transaction.atomic
def reconcile_subscription_entitlements(subscription: Subscription, *, actor_user=None):
    source_ref = f"subscription:{subscription.pk}"
    scope = _subscription_scope(subscription)
    active = _subscription_is_active(subscription)
    product_code = _subscription_product_code(subscription)
    if not product_code:
        raise ValueError(
            f"Unknown {subscription.provider_type} subscription plan_code: {subscription.plan_code}"
        )

    entitlement, _ = Entitlement.objects.update_or_create(
        account=subscription.account,
        source_type=Entitlement.SourceType.SUBSCRIPTION,
        source_ref=source_ref,
        scope_type=scope["scope_type"],
        subject_user_id=scope["subject_user_id"],
        product_code=product_code,
        feature_code="",
        limit_code="",
        defaults={
            "limit_value": None,
            "status": Entitlement.Status.ACTIVE if active else Entitlement.Status.EXPIRED,
            "portable_across_accounts": scope["portable_across_accounts"],
            "starts_at": subscription.starts_at or subscription.current_period_start,
            "ends_at": subscription.current_period_end,
            "metadata": {
                "plan_code": subscription.plan_code,
                "provider_type": subscription.provider_type,
                "subscription_uuid": str(subscription.uuid),
                "product_code": product_code,
            },
        },
    )

    source_rows = Entitlement.objects.filter(
        account=subscription.account,
        source_type=Entitlement.SourceType.SUBSCRIPTION,
        source_ref=source_ref,
    )
    source_rows.exclude(pk=entitlement.pk).update(
        status=Entitlement.Status.REVOKED,
        ends_at=timezone.now(),
    )

    create_account_audit_event(
        account=subscription.account,
        actor_user=actor_user,
        event_type="billing.subscription.reconciled",
        target_type="subscription",
        target_ref=str(subscription.uuid),
        metadata={
            "provider_type": subscription.provider_type,
            "plan_code": subscription.plan_code,
            "status": subscription.status,
        },
    )


def _stripe_status(value: str | None) -> str:
    mapping = {
        "trialing": Subscription.Status.TRIALING,
        "active": Subscription.Status.ACTIVE,
        "past_due": Subscription.Status.PAST_DUE,
        "unpaid": Subscription.Status.PAST_DUE,
        "canceled": Subscription.Status.CANCELED,
        "incomplete_expired": Subscription.Status.EXPIRED,
        "paused": Subscription.Status.PAUSED,
    }
    return mapping.get(value or "", Subscription.Status.EXPIRED)


@transaction.atomic
def sync_stripe_subscription(*, account, payload: dict, plan_code: str, actor_user=None):
    customer_id = payload.get("customer") or ""
    billing_account = upsert_billing_account(
        account=account,
        provider_type=ProviderType.STRIPE,
        provider_customer_id=customer_id,
        billing_email=(payload.get("customer_email") or ""),
        country_code=((payload.get("customer_address") or {}).get("country") or ""),
        metadata={"stripe_customer_id": customer_id},
    )
    subscription, _ = Subscription.objects.update_or_create(
        provider_type=ProviderType.STRIPE,
        provider_subscription_id=payload.get("id") or "",
        defaults={
            "account": account,
            "billing_account": billing_account,
            "plan_code": plan_code,
            "status": _stripe_status(payload.get("status")),
            "starts_at": payload.get("start_date"),
            "current_period_start": payload.get("current_period_start"),
            "current_period_end": payload.get("current_period_end"),
            "cancel_at_period_end": bool(payload.get("cancel_at_period_end")),
            "ended_at": payload.get("ended_at"),
            "provider_payload": payload,
        },
    )
    reconcile_subscription_entitlements(subscription, actor_user=actor_user)
    return subscription


@transaction.atomic
def sync_apple_subscription(*, account, payload: dict, plan_code: str, actor_user=None):
    billing_account = upsert_billing_account(
        account=account,
        provider_type=ProviderType.APPLE,
        billing_email=(account.owner_user.email if account.owner_user_id else ""),
        metadata={"apple_original_transaction_id": payload.get("original_transaction_id") or ""},
    )
    subscription, _ = Subscription.objects.update_or_create(
        provider_type=ProviderType.APPLE,
        provider_original_transaction_id=payload.get("original_transaction_id") or "",
        defaults={
            "account": account,
            "billing_account": billing_account,
            "provider_subscription_id": payload.get("transaction_id") or "",
            "plan_code": plan_code,
            "status": payload.get("status", Subscription.Status.ACTIVE),
            "starts_at": payload.get("purchase_date"),
            "current_period_start": payload.get("purchase_date"),
            "current_period_end": payload.get("expires_date"),
            "cancel_at_period_end": bool(payload.get("cancel_at_period_end")),
            "ended_at": payload.get("ended_at"),
            "provider_payload": payload,
        },
    )
    reconcile_subscription_entitlements(subscription, actor_user=actor_user)
    return subscription


def record_webhook_event(
    *,
    provider_type: str,
    event_id: str,
    event_type: str,
    payload: dict,
    request_headers: dict | None = None,
):
    event, _ = WebhookEvent.objects.get_or_create(
        provider_type=provider_type,
        event_id=event_id,
        defaults={
            "event_type": event_type,
            "payload": payload,
            "request_headers": request_headers or {},
        },
    )
    if event.event_type != event_type:
        event.event_type = event_type
        event.save(update_fields=["event_type"])
    return event
