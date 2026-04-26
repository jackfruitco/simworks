from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
import stripe

from apps.accounts.models import Account
from apps.accounts.services import get_personal_account_for_user
from apps.billing.catalog import (
    canonicalize_product_code,
    product_code_from_stripe_plan_code,
    resolve_stripe_price_id,
)
from apps.billing.models import (
    BillingAccount,
    Entitlement,
    ProviderType,
    Subscription,
    WebhookEvent,
)
from apps.billing.services.subscriptions import (
    get_active_personal_subscription,
    reconcile_subscription_entitlements,
    record_webhook_event,
    sync_stripe_subscription,
    upsert_billing_account,
)
from config.logging import get_logger

logger = get_logger(__name__)

STRIPE_API_VERSION = "2026-02-25.clover"


class ActivePersonalSubscriptionError(ValueError):
    pass


class StripeBillingConfigurationError(ValueError):
    pass


class UnknownStripePriceError(ValueError):
    pass


def configure_stripe():
    secret_key = getattr(settings, "BILLING_STRIPE_SECRET_KEY", "")
    if not secret_key:
        raise StripeBillingConfigurationError("Stripe secret key is not configured.")
    stripe.api_key = secret_key
    stripe.api_version = STRIPE_API_VERSION
    return stripe


def _stripe_object_to_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict_recursive"):
        return value.to_dict_recursive()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _stripe_get(value: Any, key: str, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _safe_metadata(*, account, user, product_code: str = "", billing_interval: str = "") -> dict:
    metadata = {
        "account_uuid": str(account.uuid),
        "user_id": str(user.id if user is not None else account.owner_user_id or ""),
        "account_type": "personal",
    }
    if product_code:
        canonical_product_code = canonicalize_product_code(product_code)
        metadata["product_code"] = canonical_product_code or product_code
    if billing_interval:
        metadata["billing_interval"] = billing_interval
    environment = getattr(settings, "EMAIL_ENVIRONMENT_NAME", "") or ""
    if environment:
        metadata["environment"] = environment
    return metadata


def _validate_return_url(value: str, *, field_name: str) -> str:
    url = (value or "").strip()
    parsed = urlparse(url)
    if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute http(s) URL.")

    base_url = (getattr(settings, "BILLING_STRIPE_RETURN_BASE_URL", "") or "").strip()
    if base_url:
        base = urlparse(base_url)
        if base.scheme not in {"http", "https"} or not base.netloc:
            raise StripeBillingConfigurationError(
                "BILLING_STRIPE_RETURN_BASE_URL must be an absolute http(s) URL."
            )
        if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            raise ValueError(f"{field_name} must match the configured billing return origin.")
    return url


def _ensure_user_personal_account(user, account):
    expected_account = get_personal_account_for_user(user)
    if account.id != expected_account.id or not account.is_personal:
        raise ValueError("Stripe web checkout is available for personal accounts only.")
    return expected_account


def get_or_create_stripe_customer_for_personal_account(*, user, account) -> BillingAccount:
    account = _ensure_user_personal_account(user, account)
    billing_account = (
        BillingAccount.objects.filter(account=account, provider_type=ProviderType.STRIPE)
        .exclude(provider_customer_id="")
        .first()
    )
    if billing_account:
        return billing_account

    stripe_client = configure_stripe()
    customer = stripe_client.Customer.create(
        email=user.email or "",
        metadata=_safe_metadata(account=account, user=user),
    )
    customer_id = _stripe_get(customer, "id", "")
    if not customer_id:
        raise StripeBillingConfigurationError("Stripe did not return a customer id.")

    return upsert_billing_account(
        account=account,
        provider_type=ProviderType.STRIPE,
        provider_customer_id=customer_id,
        billing_email=user.email or "",
        metadata={
            "stripe_customer_id": customer_id,
            "account_type": "personal",
        },
    )


def create_personal_checkout_session(
    *,
    user,
    product_code: str,
    success_url: str,
    cancel_url: str,
    billing_interval: str = "monthly",
) -> dict[str, str]:
    account = get_personal_account_for_user(user)
    if not account.is_personal:
        raise ValueError("Stripe checkout is available for personal accounts only.")

    active_subscription = get_active_personal_subscription(account)
    if active_subscription is not None:
        raise ActivePersonalSubscriptionError(
            "An active personal subscription already exists. Use billing portal to manage it."
        )

    success_url = _validate_return_url(success_url, field_name="success_url")
    cancel_url = _validate_return_url(cancel_url, field_name="cancel_url")
    canonical_product_code = canonicalize_product_code(product_code)
    price_id = resolve_stripe_price_id(canonical_product_code, billing_interval)
    billing_account = get_or_create_stripe_customer_for_personal_account(
        user=user,
        account=account,
    )

    metadata = _safe_metadata(
        account=account,
        user=user,
        product_code=canonical_product_code,
        billing_interval=billing_interval,
    )
    session_params = {
        "mode": "subscription",
        "customer": billing_account.provider_customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(account.uuid),
        "metadata": metadata,
        "subscription_data": {
            "trial_period_days": getattr(settings, "BILLING_STRIPE_TRIAL_DAYS", 14),
            "metadata": metadata,
        },
        "billing_address_collection": "required",
    }
    coupon_id = (getattr(settings, "BILLING_STRIPE_PROMO_COUPON_ID", "") or "").strip()
    if coupon_id:
        session_params["discounts"] = [{"coupon": coupon_id}]

    stripe_client = configure_stripe()
    session = stripe_client.checkout.Session.create(**session_params)
    session_id = _stripe_get(session, "id", "")
    checkout_url = _stripe_get(session, "url", "")
    if not session_id or not checkout_url:
        raise StripeBillingConfigurationError("Stripe did not return a checkout session URL.")
    return {"checkout_url": checkout_url, "session_id": session_id}


def create_customer_portal_session(*, user, return_url: str) -> dict[str, str]:
    account = get_personal_account_for_user(user)
    if not account.is_personal:
        raise ValueError("Stripe customer portal is available for personal accounts only.")
    return_url = _validate_return_url(return_url, field_name="return_url")
    billing_account = (
        BillingAccount.objects.filter(account=account, provider_type=ProviderType.STRIPE)
        .exclude(provider_customer_id="")
        .first()
    )
    if billing_account is None:
        raise BillingAccount.DoesNotExist("No Stripe billing customer exists.")

    stripe_client = configure_stripe()
    session = stripe_client.billing_portal.Session.create(
        customer=billing_account.provider_customer_id,
        return_url=return_url,
    )
    session_id = _stripe_get(session, "id", "")
    portal_url = _stripe_get(session, "url", "")
    if not session_id or not portal_url:
        raise StripeBillingConfigurationError("Stripe did not return a portal session URL.")
    return {"portal_url": portal_url, "session_id": session_id}


def _construct_stripe_event(payload_bytes: bytes, signature_header: str) -> dict:
    secret = getattr(settings, "BILLING_STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise StripeBillingConfigurationError("Stripe webhook secret is not configured.")
    event = stripe.Webhook.construct_event(
        payload=payload_bytes,
        sig_header=signature_header,
        secret=secret,
        tolerance=stripe.Webhook.DEFAULT_TOLERANCE,
    )
    return _stripe_object_to_dict(event)


def verify_stripe_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    try:
        stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature_header,
            secret=secret,
            tolerance=stripe.Webhook.DEFAULT_TOLERANCE,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return False
    return True


def _resolve_account_from_payload(payload: dict):
    obj = (payload.get("data") or {}).get("object") or {}
    metadata = obj.get("metadata") or {}
    account_uuid = metadata.get("account_uuid") or ""
    customer_id = obj.get("customer") or ""
    if account_uuid:
        return Account.objects.filter(uuid=account_uuid).first()
    if customer_id:
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


def _resolve_account_from_subscription(subscription: dict):
    metadata = subscription.get("metadata") or {}
    account_uuid = metadata.get("account_uuid") or ""
    if account_uuid:
        account = Account.objects.filter(uuid=account_uuid).first()
        if account:
            return account
    customer_id = subscription.get("customer") or ""
    if customer_id:
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


def _normalize_subscription_payload(subscription: Any) -> dict:
    payload = _stripe_object_to_dict(subscription).copy()
    for field in (
        "start_date",
        "current_period_start",
        "current_period_end",
        "ended_at",
    ):
        payload[field] = _timestamp_to_datetime(payload.get(field))
    return payload


def _stripe_subscription_price_id(subscription: dict) -> str:
    items = (subscription.get("items") or {}).get("data") or []
    if not items:
        return ""
    price = (items[0] or {}).get("price") or {}
    return price.get("id") or ""


def _sync_subscription_from_payload(*, account, subscription: Any):
    subscription_payload = _normalize_subscription_payload(subscription)
    price_id = _stripe_subscription_price_id(subscription_payload)
    product_code = product_code_from_stripe_plan_code(price_id)
    if not product_code:
        _fail_closed_existing_subscription(subscription_payload)
        raise UnknownStripePriceError("Unknown Stripe price id")
    return sync_stripe_subscription(
        account=account,
        payload=subscription_payload,
        plan_code=price_id,
    )


def _revoke_subscription_entitlements(subscription: Subscription):
    now = timezone.now()
    Entitlement.objects.filter(
        source_type=Entitlement.SourceType.SUBSCRIPTION,
        source_ref=f"subscription:{subscription.pk}",
    ).update(status=Entitlement.Status.EXPIRED, ends_at=now)


def _expire_and_reconcile_subscription(subscription: Subscription):
    now = timezone.now()
    subscription.status = Subscription.Status.EXPIRED
    subscription.ended_at = subscription.ended_at or now
    subscription.current_period_end = now
    subscription.save(update_fields=["status", "ended_at", "current_period_end"])
    try:
        reconcile_subscription_entitlements(subscription)
    except ValueError:
        _revoke_subscription_entitlements(subscription)


def _fail_closed_existing_subscription(subscription_payload: dict) -> bool:
    provider_subscription_id = subscription_payload.get("id") or ""
    if not provider_subscription_id:
        return False
    subscription = Subscription.objects.filter(
        provider_type=ProviderType.STRIPE,
        provider_subscription_id=provider_subscription_id,
    ).first()
    if subscription is None:
        return False
    _expire_and_reconcile_subscription(subscription)
    return True


def _handle_checkout_session_completed(obj: dict):
    metadata = obj.get("metadata") or {}
    account_uuid = metadata.get("account_uuid") or obj.get("client_reference_id") or ""
    account = Account.objects.filter(uuid=account_uuid).first() if account_uuid else None
    if account is None:
        raise ValueError("Unable to resolve account from Stripe checkout session")

    customer_id = obj.get("customer") or ""
    if customer_id:
        upsert_billing_account(
            account=account,
            provider_type=ProviderType.STRIPE,
            provider_customer_id=customer_id,
            billing_email=obj.get("customer_email") or "",
            metadata={
                "stripe_customer_id": customer_id,
                "account_type": "personal",
            },
        )

    subscription_id = obj.get("subscription") or ""
    if subscription_id:
        stripe_client = configure_stripe()
        subscription = stripe_client.Subscription.retrieve(subscription_id)
        subscription_payload = _stripe_object_to_dict(subscription)
        subscription_account = _resolve_account_from_subscription(subscription_payload) or account
        _sync_subscription_from_payload(
            account=subscription_account,
            subscription=subscription_payload,
        )


def _handle_invoice_subscription_status(obj: dict, *, status: str | None = None):
    provider_subscription_id = obj.get("subscription") or ""
    if not provider_subscription_id or not status:
        return
    subscription = Subscription.objects.filter(
        provider_type=ProviderType.STRIPE,
        provider_subscription_id=provider_subscription_id,
    ).first()
    if subscription is None:
        return
    subscription.status = status
    subscription.save(update_fields=["status"])
    try:
        reconcile_subscription_entitlements(subscription)
    except ValueError:
        _revoke_subscription_entitlements(subscription)


def process_stripe_webhook(
    *,
    payload_bytes: bytes,
    signature_header: str,
    verify_signature: bool = True,
):
    try:
        payload = (
            _construct_stripe_event(payload_bytes, signature_header)
            if verify_signature
            else json.loads(payload_bytes.decode("utf-8"))
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise ValueError("Invalid Stripe signature") from exc
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
    try:
        if event_type.startswith("customer.subscription."):
            account = _resolve_account_from_payload(payload)
            if account is None:
                raise ValueError("Unable to resolve account from Stripe payload")
            _sync_subscription_from_payload(account=account, subscription=obj)
        elif event_type == "checkout.session.completed":
            _handle_checkout_session_completed(obj)
        elif event_type == "invoice.payment_failed":
            _handle_invoice_subscription_status(obj, status=Subscription.Status.PAST_DUE)
        elif event_type == "invoice.payment_succeeded":
            _handle_invoice_subscription_status(obj)

        event.status = WebhookEvent.Status.PROCESSED
        event.processed_at = timezone.now()
        event.processing_error = ""
        event.save(update_fields=["status", "processed_at", "processing_error"])
    except Exception as exc:
        logger.warning(
            "stripe.webhook_processing_failed",
            event_id=event_id,
            event_type=event_type,
            error=str(exc),
        )
        event.status = WebhookEvent.Status.FAILED
        event.processing_error = str(exc)
        event.save(update_fields=["status", "processing_error"])
    return event
