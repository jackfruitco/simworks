from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BillingAccountOut(BaseModel):
    uuid: str
    provider_type: str
    provider_customer_id: str
    billing_email: str
    country_code: str
    is_active: bool


class SubscriptionOut(BaseModel):
    uuid: str
    provider_type: str
    plan_code: str
    status: str
    provider_subscription_id: str
    provider_original_transaction_id: str
    cancel_at_period_end: bool
    current_period_end: datetime | None = None


class EntitlementOut(BaseModel):
    uuid: str
    source_type: str
    source_ref: str
    scope_type: str
    subject_user_id: int | None = None
    product_code: str
    feature_code: str = ""
    limit_code: str = ""
    limit_value: int | None = None
    status: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class BillingSummaryOut(BaseModel):
    account_uuid: str
    billing_accounts: list[BillingAccountOut] = Field(default_factory=list)
    subscriptions: list[SubscriptionOut] = Field(default_factory=list)
    entitlements: list[EntitlementOut] = Field(default_factory=list)


class StripeWebhookReceiptOut(BaseModel):
    event_id: str
    status: str


class AppleTransactionIn(BaseModel):
    transaction_id: str
    original_transaction_id: str
    product_id: str
    status: str = "active"
    purchase_date: datetime | None = None
    expires_date: datetime | None = None
    ended_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CheckoutSessionIn(BaseModel):
    product_code: str
    billing_interval: Literal["monthly"] = "monthly"
    success_url: str
    cancel_url: str


class CheckoutSessionOut(BaseModel):
    checkout_url: str
    session_id: str


class CustomerPortalSessionIn(BaseModel):
    return_url: str


class CustomerPortalSessionOut(BaseModel):
    portal_url: str
    session_id: str
