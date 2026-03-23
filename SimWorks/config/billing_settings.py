from __future__ import annotations

import json
import os

from .settings_parsers import bool_from_env


def _json_object_from_env(name: str, default: dict) -> dict:
    value = os.getenv(name)
    if not value:
        return dict(default)
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError(f"Environment variable {name} must decode to a JSON object.")
    return loaded


BILLING_STRIPE_PRICE_PLAN_MAP = _json_object_from_env(
    "BILLING_STRIPE_PRICE_PLAN_MAP",
    default={},
)
BILLING_APPLE_PRODUCT_PLAN_MAP = _json_object_from_env(
    "BILLING_APPLE_PRODUCT_PLAN_MAP",
    default={},
)
BILLING_STRIPE_WEBHOOK_SECRET = os.getenv("BILLING_STRIPE_WEBHOOK_SECRET", "")
BILLING_STRIPE_SECRET_KEY = os.getenv("BILLING_STRIPE_SECRET_KEY", "")
BILLING_STRIPE_CHECKOUT_ENABLED = bool_from_env("BILLING_STRIPE_CHECKOUT_ENABLED", default=False)
