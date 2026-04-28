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
    CustomerPortalSessionIn,
    CustomerPortalSessionOut,
    StripeWebhookReceiptOut,
)
from apps.accounts.services import get_personal_account_for_user
from apps.billing.models import BillingAccount
from apps.billing.providers.apple import sync_apple_transaction_event
from apps.billing.providers.stripe import (
    ActivePersonalSubscriptionError,
    StripeBillingConfigurationError,
    create_customer_portal_session,
    create_personal_checkout_session,
    process_stripe_webhook,
)
from config.logging import get_logger

logger = get_logger(__name__)

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
    try:
        session = create_personal_checkout_session(
            user=request.auth,
            product_code=body.product_code,
            billing_interval=body.billing_interval,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    except ActivePersonalSubscriptionError as exc:
        raise HttpError(409, str(exc)) from None
    except StripeBillingConfigurationError as exc:
        raise HttpError(400, str(exc)) from None
    except ValueError as exc:
        raise HttpError(400, str(exc)) from None
    except Exception as exc:
        logger.exception(
            "stripe.checkout_session_failed",
            user_id=getattr(request.auth, "id", None),
            product_code=body.product_code,
        )
        raise HttpError(500, "Stripe checkout session creation failed") from exc
    return CheckoutSessionOut(**session)


@router.post(
    "/stripe/customer-portal-session/",
    response=CustomerPortalSessionOut,
    summary="Create a Stripe customer portal session for a personal account",
)
def create_portal_session(
    request: HttpRequest, body: CustomerPortalSessionIn
) -> CustomerPortalSessionOut:
    if not getattr(settings, "BILLING_STRIPE_PORTAL_ENABLED", False):
        raise HttpError(404, "Stripe customer portal is not enabled")
    try:
        session = create_customer_portal_session(user=request.auth, return_url=body.return_url)
    except BillingAccount.DoesNotExist as exc:
        raise HttpError(404, "No Stripe billing customer exists") from exc
    except StripeBillingConfigurationError as exc:
        raise HttpError(400, str(exc)) from None
    except ValueError as exc:
        raise HttpError(400, str(exc)) from None
    except Exception as exc:
        logger.exception(
            "stripe.customer_portal_session_failed",
            user_id=getattr(request.auth, "id", None),
        )
        raise HttpError(500, "Stripe customer portal session creation failed") from exc
    return CustomerPortalSessionOut(**session)
