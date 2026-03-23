from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.billing import (
    AppleTransactionIn,
    CheckoutSessionIn,
    CheckoutSessionOut,
    StripeWebhookReceiptOut,
)
from apps.accounts.services import get_personal_account_for_user
from apps.billing.providers.apple import sync_apple_transaction_event
from apps.billing.providers.stripe import process_stripe_webhook

router = Router(tags=["billing"], auth=DualAuth())


@router.post(
    "/stripe/webhook/",
    auth=None,
    response=StripeWebhookReceiptOut,
    summary="Receive Stripe webhook events",
)
def stripe_webhook(request: HttpRequest) -> StripeWebhookReceiptOut:
    try:
        event = process_stripe_webhook(
            payload_bytes=request.body,
            signature_header=request.headers.get("Stripe-Signature", ""),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from None
    return StripeWebhookReceiptOut(event_id=event.event_id, status=event.status)


@router.post(
    "/apple/sync/",
    response=StripeWebhookReceiptOut,
    summary="Sync an Apple subscription transaction for the signed-in user",
)
def apple_sync(request: HttpRequest, body: AppleTransactionIn) -> StripeWebhookReceiptOut:
    user = request.auth
    account = get_personal_account_for_user(user)
    event = sync_apple_transaction_event(
        account=account, payload=body.model_dump(exclude_none=True)
    )
    return StripeWebhookReceiptOut(event_id=event.event_id, status=event.status)


@router.post(
    "/stripe/checkout-session/",
    response=CheckoutSessionOut,
    summary="Create a Stripe checkout session for a personal plan",
)
def create_checkout_session(request: HttpRequest, body: CheckoutSessionIn) -> CheckoutSessionOut:
    if not getattr(settings, "BILLING_STRIPE_CHECKOUT_ENABLED", False):
        raise HttpError(404, "Stripe checkout is not enabled")
    raise HttpError(
        501,
        "Stripe checkout session creation is scaffolded but not yet configured in this environment",
    )
