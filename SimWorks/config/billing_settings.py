from __future__ import annotations

import json
import os

from .settings_parsers import bool_from_env, int_from_env


def _json_object_from_env(name: str, default: dict) -> dict:
    value = os.getenv(name)
    if not value:
        return dict(default)
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError(f"Environment variable {name} must decode to a JSON object.")
    for key, mapped_value in loaded.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"Environment variable {name} keys must be non-empty strings.")
        if not isinstance(mapped_value, str) or not mapped_value.strip():
            raise ValueError(f"Environment variable {name} values must be non-empty strings.")
    return loaded


BILLING_STRIPE_PRICE_PLAN_MAP = _json_object_from_env(
    "BILLING_STRIPE_PRICE_PLAN_MAP",
    default={},
)
BILLING_STRIPE_PROMO_COUPON_MAP = _json_object_from_env(
    "BILLING_STRIPE_PROMO_COUPON_MAP",
    default={},
)
BILLING_APPLE_PRODUCT_PLAN_MAP = _json_object_from_env(
    "BILLING_APPLE_PRODUCT_PLAN_MAP",
    default={},
)
BILLING_STRIPE_WEBHOOK_SECRET = os.getenv("BILLING_STRIPE_WEBHOOK_SECRET", "")
BILLING_STRIPE_SECRET_KEY = os.getenv("BILLING_STRIPE_SECRET_KEY", "")
BILLING_STRIPE_CHECKOUT_ENABLED = bool_from_env("BILLING_STRIPE_CHECKOUT_ENABLED", default=False)
BILLING_STRIPE_PORTAL_ENABLED = bool_from_env("BILLING_STRIPE_PORTAL_ENABLED", default=False)
BILLING_STRIPE_PROMO_COUPON_ID = os.getenv("BILLING_STRIPE_PROMO_COUPON_ID", "").strip()
BILLING_STRIPE_TRIAL_DAYS = int_from_env("BILLING_STRIPE_TRIAL_DAYS", default=14, minimum=0)
BILLING_STRIPE_RETURN_BASE_URL = os.getenv("BILLING_STRIPE_RETURN_BASE_URL", "").strip()
