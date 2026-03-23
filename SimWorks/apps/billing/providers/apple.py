from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.billing.models import ProviderType, Subscription, WebhookEvent
from apps.billing.services.subscriptions import record_webhook_event, sync_apple_subscription


def sync_apple_transaction_event(*, account, payload: dict):
    event_id = payload.get("transaction_id") or payload.get("original_transaction_id") or ""
    event = record_webhook_event(
        provider_type=ProviderType.APPLE,
        event_id=event_id,
        event_type="transaction.sync",
        payload=payload,
    )
    if event.status == WebhookEvent.Status.PROCESSED:
        return event

    product_id = payload.get("product_id") or ""
    plan_code = getattr(settings, "BILLING_APPLE_PRODUCT_PLAN_MAP", {}).get(product_id, "")
    if not plan_code:
        event.status = WebhookEvent.Status.FAILED
        event.processing_error = "Unknown Apple product id"
        event.save(update_fields=["status", "processing_error"])
        return event

    normalized = dict(payload)
    for field_name in ("purchase_date", "expires_date", "ended_at"):
        value = normalized.get(field_name)
        if isinstance(value, str):
            normalized[field_name] = timezone.datetime.fromisoformat(value)

    status = payload.get("status") or Subscription.Status.ACTIVE
    normalized["status"] = status
    sync_apple_subscription(account=account, payload=normalized, plan_code=plan_code)

    event.status = WebhookEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "processed_at"])
    return event
