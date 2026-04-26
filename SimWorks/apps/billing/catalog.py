from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class ProductCode(StrEnum):
    CHATLAB_GO = "chatlab_go"
    CHATLAB_PLUS = "chatlab_plus"
    TRAINERLAB_GO = "trainerlab_go"
    TRAINERLAB_PLUS = "trainerlab_plus"
    MEDSIM_ONE = "medsim_one"
    MEDSIM_ONE_PLUS = "medsim_one_plus"


@dataclass(frozen=True)
class ProductDefinition:
    code: str
    display_name: str
    seat_gated: bool
    included_labs: tuple[str, ...] = ()
    apple_product_ids: tuple[str, ...] = ()
    stripe_plan_codes: tuple[str, ...] = ()


PRODUCTS: dict[str, ProductDefinition] = {
    ProductCode.CHATLAB_GO.value: ProductDefinition(
        code=ProductCode.CHATLAB_GO.value,
        display_name="ChatLab Go",
        seat_gated=True,
        included_labs=("chatlab",),
        apple_product_ids=("com.jackfruitco.medsim.chatlab.go.monthly",),
        stripe_plan_codes=("price_chatlab_go_monthly", "chatlab_go_monthly"),
    ),
    ProductCode.CHATLAB_PLUS.value: ProductDefinition(
        code=ProductCode.CHATLAB_PLUS.value,
        display_name="ChatLab Plus",
        seat_gated=True,
        included_labs=("chatlab",),
        apple_product_ids=(
            "com.jackfruitco.medsim.chatlab.plus.monthly",
            "com.jackfruitco.medsim.individual.plus.monthly",
        ),
        stripe_plan_codes=("price_chatlab_plus_monthly", "chatlab_plus_monthly"),
    ),
    ProductCode.TRAINERLAB_GO.value: ProductDefinition(
        code=ProductCode.TRAINERLAB_GO.value,
        display_name="TrainerLab Go",
        seat_gated=True,
        included_labs=("trainerlab",),
        apple_product_ids=("com.jackfruitco.medsim.trainerlab.go.monthly",),
        stripe_plan_codes=("price_trainerlab_go_monthly", "trainerlab_go_monthly"),
    ),
    ProductCode.TRAINERLAB_PLUS.value: ProductDefinition(
        code=ProductCode.TRAINERLAB_PLUS.value,
        display_name="TrainerLab Plus",
        seat_gated=True,
        included_labs=("trainerlab",),
        apple_product_ids=("com.jackfruitco.medsim.trainerlab.plus.monthly",),
        stripe_plan_codes=("price_trainerlab_plus_monthly", "trainerlab_plus_monthly"),
    ),
    ProductCode.MEDSIM_ONE.value: ProductDefinition(
        code=ProductCode.MEDSIM_ONE.value,
        display_name="MedSim One",
        seat_gated=True,
        included_labs=("chatlab", "trainerlab"),
        apple_product_ids=("com.jackfruitco.medsim.one.monthly",),
        stripe_plan_codes=("price_medsim_one_monthly", "medsim_one_monthly"),
    ),
    ProductCode.MEDSIM_ONE_PLUS.value: ProductDefinition(
        code=ProductCode.MEDSIM_ONE_PLUS.value,
        display_name="MedSim One Plus",
        seat_gated=True,
        included_labs=("chatlab", "trainerlab"),
        apple_product_ids=("com.jackfruitco.medsim.one.plus.monthly",),
        stripe_plan_codes=("price_medsim_one_plus_monthly", "medsim_one_plus_monthly"),
    ),
}

LEGACY_PRODUCT_CODE_ALIASES = {
    "chatlab": ProductCode.CHATLAB_GO.value,
    "trainerlab": ProductCode.TRAINERLAB_GO.value,
}

APPLE_PRODUCT_ID_TO_PRODUCT_CODE = {
    product_id: product.code
    for product in PRODUCTS.values()
    for product_id in product.apple_product_ids
}

STRIPE_PLAN_CODE_TO_PRODUCT_CODE = {
    plan_code: product.code
    for product in PRODUCTS.values()
    for plan_code in product.stripe_plan_codes
}

WEB_PERSONAL_PRODUCT_CODES = (
    ProductCode.CHATLAB_GO.value,
    ProductCode.TRAINERLAB_GO.value,
    ProductCode.MEDSIM_ONE.value,
)

BillingInterval = Literal["monthly"]


def all_product_codes() -> tuple[str, ...]:
    return tuple(PRODUCTS.keys())


def is_valid_product_code(code: str | None) -> bool:
    return (code or "") in PRODUCTS


def canonicalize_product_code(code: str | None) -> str:
    raw = (code or "").strip()
    if raw in PRODUCTS:
        return raw
    return LEGACY_PRODUCT_CODE_ALIASES.get(raw, "")


def get_product(code: str) -> ProductDefinition:
    canonical_code = canonicalize_product_code(code)
    if canonical_code not in PRODUCTS:
        raise KeyError(f"Unknown product code: {code}")
    return PRODUCTS[canonical_code]


def product_code_from_apple_product_id(product_id: str | None) -> str:
    return APPLE_PRODUCT_ID_TO_PRODUCT_CODE.get((product_id or "").strip(), "")


def product_code_from_stripe_plan_code(plan_code: str | None) -> str:
    normalized = (plan_code or "").strip()
    product_code = STRIPE_PLAN_CODE_TO_PRODUCT_CODE.get(normalized, "")
    if product_code:
        return product_code
    return stripe_product_code_from_price_id(normalized)


def _stripe_price_plan_map() -> dict[str, str]:
    from django.conf import settings

    value = getattr(settings, "BILLING_STRIPE_PRICE_PLAN_MAP", {}) or {}
    if not isinstance(value, dict):
        raise ValueError("BILLING_STRIPE_PRICE_PLAN_MAP must be a JSON object.")
    normalized: dict[str, str] = {}
    for key, price_id in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("BILLING_STRIPE_PRICE_PLAN_MAP keys must be non-empty strings.")
        if not isinstance(price_id, str) or not price_id.strip():
            raise ValueError("BILLING_STRIPE_PRICE_PLAN_MAP values must be non-empty strings.")
        normalized[key.strip()] = price_id.strip()
    return normalized


def resolve_stripe_price_id(
    product_code: str | None,
    interval: BillingInterval = "monthly",
) -> str:
    canonical_product_code = canonicalize_product_code(product_code)
    if canonical_product_code not in WEB_PERSONAL_PRODUCT_CODES:
        raise ValueError(f"Unsupported web personal product_code: {product_code}")
    if interval != "monthly":
        raise ValueError("Only monthly billing_interval is supported.")
    lookup_key = f"{canonical_product_code}:{interval}"
    price_id = _stripe_price_plan_map().get(lookup_key, "")
    if not price_id:
        raise ValueError(f"Missing Stripe price mapping for {lookup_key}.")
    return price_id


def stripe_product_code_from_price_id(price_id: str | None) -> str:
    normalized_price_id = (price_id or "").strip()
    if not normalized_price_id:
        return ""
    for key, mapped_price_id in _stripe_price_plan_map().items():
        if mapped_price_id != normalized_price_id:
            continue
        product_code, _, interval = key.partition(":")
        if interval != "monthly":
            continue
        canonical_product_code = canonicalize_product_code(product_code)
        if canonical_product_code in WEB_PERSONAL_PRODUCT_CODES:
            return canonical_product_code
    return ""


def product_includes_lab(product_code: str | None, lab_slug: str | None) -> bool:
    canonical_product_code = canonicalize_product_code(product_code)
    if canonical_product_code not in PRODUCTS:
        return False
    normalized_lab_slug = (lab_slug or "").strip()
    return normalized_lab_slug in PRODUCTS[canonical_product_code].included_labs


def product_codes_for_lab(lab_slug: str | None) -> tuple[str, ...]:
    normalized_lab_slug = (lab_slug or "").strip()
    if not normalized_lab_slug:
        return ()
    return tuple(
        product.code
        for product in PRODUCTS.values()
        if normalized_lab_slug in product.included_labs
    )
