from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json

from django.utils import timezone

from apps.accounts.models import Account
from apps.billing.catalog import (
    canonicalize_product_code,
    product_code_from_stripe_plan_code,
    resolve_stripe_price_id,
    resolve_stripe_promo_coupon_id,
)
from apps.billing.models import BillingAccount, ProviderType, Subscription, WebhookEvent
from apps.billing.services.subscriptions import record_webhook_event, sync_stripe_subscription


def verify_stripe_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header or not secret:
        return False
    timestamp = None
    signatures = []
    for part in signature_header.split(","):
        key, _, value = part.partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        return False
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode()
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def _resolve_account_from_payload(payload: dict):
    obj = (payload.get("data") or {}).get("object") or {}
    metadata = obj.get("metadata") or {}
    account_uuid = metadata.get("account_uuid") or ""
    customer_id = obj.get("customer") or ""
    if account_uuid:
        return Account.objects.filter(uuid=account_uuid).first()
    if customer_id:
        from apps.billing.models import BillingAccount

        billing_account = (
            BillingAccount.objects.filter(
                provider_type=ProviderType.STRIPE,
                provider_customer_id=customer_id,
            )
            .select_related("account")
            .first()
        )
        if billing_account:
            return billing_account.account
    return None


def _timestamp_to_datetime(value):
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _get_stripe_checkout_session_api():
    import stripe

    return stripe.checkout.Session


def _stripe_session_value(session, key: str) -> str:
    if isinstance(session, dict):
        return str(session.get(key) or "")
    return str(getattr(session, key, "") or "")


def create_personal_checkout_session(
    *,
    account,
    product_code: str,
    billing_interval: str = "monthly",
    success_url: str,
    cancel_url: str,
) -> dict[str, str]:
    from django.conf import settings

    secret_key = getattr(settings, "BILLING_STRIPE_SECRET_KEY", "")
    if not secret_key:
        raise ValueError("Stripe secret key is not configured")

    canonical_product_code = canonicalize_product_code(product_code)
    if not canonical_product_code:
        raise ValueError("Unknown product code")

    interval = (billing_interval or "monthly").strip() or "monthly"
    price_id = resolve_stripe_price_id(canonical_product_code, interval)
    if not price_id:
        raise ValueError("Stripe price is not configured for this product")

    session_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(account.uuid),
        "metadata": {
            "account_uuid": str(account.uuid),
            "product_code": canonical_product_code,
            "billing_interval": interval,
        },
        "subscription_data": {
            "metadata": {
                "account_uuid": str(account.uuid),
                "product_code": canonical_product_code,
                "billing_interval": interval,
            },
        },
    }

    billing_account = (
        BillingAccount.objects.filter(
            account=account,
            provider_type=ProviderType.STRIPE,
            provider_customer_id__gt="",
            is_active=True,
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    if billing_account:
        session_params["customer"] = billing_account.provider_customer_id
    elif account.owner_user_id and account.owner_user.email:
        session_params["customer_email"] = account.owner_user.email

    coupon_id = resolve_stripe_promo_coupon_id(canonical_product_code, interval)
    if coupon_id:
        session_params["discounts"] = [{"coupon": coupon_id}]

    checkout_session = _get_stripe_checkout_session_api().create(
        api_key=secret_key,
        **session_params,
    )
    return {
        "session_id": _stripe_session_value(checkout_session, "id"),
        "url": _stripe_session_value(checkout_session, "url"),
    }


def process_stripe_webhook(*, payload_bytes: bytes, signature_header: str):
    from django.conf import settings

    secret = getattr(settings, "BILLING_STRIPE_WEBHOOK_SECRET", "")
    if not verify_stripe_signature(payload_bytes, signature_header, secret):
        raise ValueError("Invalid Stripe signature")

    payload = json.loads(payload_bytes.decode("utf-8"))
    event_id = payload.get("id") or ""
    event_type = payload.get("type") or ""
    event = record_webhook_event(
        provider_type=ProviderType.STRIPE,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    if event.status == WebhookEvent.Status.PROCESSED:
        return event

    obj = (payload.get("data") or {}).get("object") or {}
    account = _resolve_account_from_payload(payload)
    if account is None:
        event.status = WebhookEvent.Status.FAILED
        event.processing_error = "Unable to resolve account from Stripe payload"
        event.save(update_fields=["status", "processing_error"])
        return event

    if event_type.startswith("customer.subscription."):
        obj["start_date"] = _timestamp_to_datetime(obj.get("start_date"))
        obj["current_period_start"] = _timestamp_to_datetime(obj.get("current_period_start"))
        obj["current_period_end"] = _timestamp_to_datetime(obj.get("current_period_end"))
        obj["ended_at"] = _timestamp_to_datetime(obj.get("ended_at"))
        price_id = ((obj.get("items") or {}).get("data") or [{}])[0].get("price", {}).get(
            "id"
        ) or ""
        product_code = product_code_from_stripe_plan_code(price_id)
        if not product_code:
            event.status = WebhookEvent.Status.FAILED
            event.processing_error = "Unknown Stripe price id"
            event.save(update_fields=["status", "processing_error"])
            return event
        sync_stripe_subscription(account=account, payload=obj, plan_code=price_id)
    elif event_type == "invoice.payment_failed":
        provider_subscription_id = obj.get("subscription") or ""
        if provider_subscription_id:
            Subscription.objects.filter(
                provider_type=ProviderType.STRIPE,
                provider_subscription_id=provider_subscription_id,
            ).update(status=Subscription.Status.PAST_DUE)

    event.status = WebhookEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "processed_at"])
    return event
