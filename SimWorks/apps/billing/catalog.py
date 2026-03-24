from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
    apple_product_ids: tuple[str, ...] = ()
    stripe_plan_codes: tuple[str, ...] = ()


PRODUCTS: dict[str, ProductDefinition] = {
    ProductCode.CHATLAB_GO.value: ProductDefinition(
        code=ProductCode.CHATLAB_GO.value,
        display_name="ChatLab Go",
        seat_gated=True,
        apple_product_ids=("com.jackfruitco.medsim.chatlab.go.monthly",),
        stripe_plan_codes=("price_chatlab_go_monthly", "chatlab_go_monthly"),
    ),
    ProductCode.CHATLAB_PLUS.value: ProductDefinition(
        code=ProductCode.CHATLAB_PLUS.value,
        display_name="ChatLab Plus",
        seat_gated=True,
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
        apple_product_ids=("com.jackfruitco.medsim.trainerlab.go.monthly",),
        stripe_plan_codes=("price_trainerlab_go_monthly", "trainerlab_go_monthly"),
    ),
    ProductCode.TRAINERLAB_PLUS.value: ProductDefinition(
        code=ProductCode.TRAINERLAB_PLUS.value,
        display_name="TrainerLab Plus",
        seat_gated=True,
        apple_product_ids=("com.jackfruitco.medsim.trainerlab.plus.monthly",),
        stripe_plan_codes=("price_trainerlab_plus_monthly", "trainerlab_plus_monthly"),
    ),
    ProductCode.MEDSIM_ONE.value: ProductDefinition(
        code=ProductCode.MEDSIM_ONE.value,
        display_name="MedSim One",
        seat_gated=True,
        apple_product_ids=("com.jackfruitco.medsim.one.monthly",),
        stripe_plan_codes=("price_medsim_one_monthly", "medsim_one_monthly"),
    ),
    ProductCode.MEDSIM_ONE_PLUS.value: ProductDefinition(
        code=ProductCode.MEDSIM_ONE_PLUS.value,
        display_name="MedSim One Plus",
        seat_gated=True,
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
    return STRIPE_PLAN_CODE_TO_PRODUCT_CODE.get((plan_code or "").strip(), "")
