from __future__ import annotations

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from apps.accounts.services import get_personal_account_for_user
from apps.billing.catalog import WEB_PERSONAL_PRODUCT_CODES, get_product
from apps.billing.models import BillingAccount, ProviderType
from apps.billing.services.subscriptions import get_active_personal_subscription


def _absolute_url(request, view_name: str) -> str:
    return request.build_absolute_uri(reverse(view_name))


@login_required
def billing_home(request):
    personal_account = get_personal_account_for_user(request.user)
    active_subscription = get_active_personal_subscription(personal_account)
    stripe_customer_exists = (
        BillingAccount.objects.filter(
            account=personal_account,
            provider_type=ProviderType.STRIPE,
        )
        .exclude(provider_customer_id="")
        .exists()
    )
    products = [
        {
            "code": product_code,
            "name": get_product(product_code).display_name,
            "labs": get_product(product_code).included_labs,
        }
        for product_code in WEB_PERSONAL_PRODUCT_CODES
    ]
    return render(
        request,
        "billing/home.html",
        {
            "active_subscription": active_subscription,
            "checkout_enabled": getattr(settings, "BILLING_STRIPE_CHECKOUT_ENABLED", False),
            "portal_enabled": getattr(settings, "BILLING_STRIPE_PORTAL_ENABLED", False),
            "products": products,
            "stripe_customer_exists": stripe_customer_exists,
            "success_url": _absolute_url(request, "billing:success"),
            "cancel_url": _absolute_url(request, "billing:return"),
            "return_url": _absolute_url(request, "billing:return"),
        },
    )


@login_required
def billing_success(request):
    return render(request, "billing/success.html")


@login_required
def billing_return(request):
    return render(request, "billing/return.html")
