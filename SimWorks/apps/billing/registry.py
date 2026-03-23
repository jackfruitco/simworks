from __future__ import annotations

from dataclasses import dataclass, field


PRODUCT_CHATLAB = "chatlab"
PRODUCT_TRAINERLAB = "trainerlab"

FEATURE_EXPORTS = "exports"
FEATURE_ANALYTICS = "analytics"
FEATURE_ADVANCED_CASES = "advanced_cases"
FEATURE_INSTRUCTOR_TOOLS = "instructor_tools"

LIMIT_MONTHLY_RUNS = "monthly_runs"
LIMIT_MONTHLY_AI_MESSAGES = "monthly_ai_messages"
LIMIT_IMAGE_GENERATIONS = "image_generations"

PLAN_PERSONAL_FREE = "personal_free"
PLAN_PERSONAL_PLUS = "personal_plus"
PLAN_PERSONAL_PRO = "personal_pro"


@dataclass(frozen=True)
class ProductDefinition:
    code: str
    display_name: str


@dataclass(frozen=True)
class FeatureDefinition:
    code: str
    product_code: str
    display_name: str


@dataclass(frozen=True)
class LimitDefinition:
    code: str
    product_code: str
    display_name: str


@dataclass(frozen=True)
class PlanDefinition:
    code: str
    display_name: str
    product_codes: tuple[str, ...] = ()
    feature_codes: tuple[str, ...] = ()
    limit_values: dict[str, int] = field(default_factory=dict)


PRODUCTS = {
    PRODUCT_CHATLAB: ProductDefinition(code=PRODUCT_CHATLAB, display_name="ChatLab"),
    PRODUCT_TRAINERLAB: ProductDefinition(code=PRODUCT_TRAINERLAB, display_name="TrainerLab"),
}

FEATURES = {
    FEATURE_EXPORTS: FeatureDefinition(
        code=FEATURE_EXPORTS,
        product_code=PRODUCT_CHATLAB,
        display_name="Exports",
    ),
    FEATURE_ANALYTICS: FeatureDefinition(
        code=FEATURE_ANALYTICS,
        product_code=PRODUCT_CHATLAB,
        display_name="Analytics",
    ),
    FEATURE_ADVANCED_CASES: FeatureDefinition(
        code=FEATURE_ADVANCED_CASES,
        product_code=PRODUCT_CHATLAB,
        display_name="Advanced Cases",
    ),
    FEATURE_INSTRUCTOR_TOOLS: FeatureDefinition(
        code=FEATURE_INSTRUCTOR_TOOLS,
        product_code=PRODUCT_TRAINERLAB,
        display_name="Instructor Tools",
    ),
}

LIMITS = {
    LIMIT_MONTHLY_RUNS: LimitDefinition(
        code=LIMIT_MONTHLY_RUNS,
        product_code=PRODUCT_CHATLAB,
        display_name="Monthly Runs",
    ),
    LIMIT_MONTHLY_AI_MESSAGES: LimitDefinition(
        code=LIMIT_MONTHLY_AI_MESSAGES,
        product_code=PRODUCT_CHATLAB,
        display_name="Monthly AI Messages",
    ),
    LIMIT_IMAGE_GENERATIONS: LimitDefinition(
        code=LIMIT_IMAGE_GENERATIONS,
        product_code=PRODUCT_CHATLAB,
        display_name="Image Generations",
    ),
}

PLANS = {
    PLAN_PERSONAL_FREE: PlanDefinition(
        code=PLAN_PERSONAL_FREE,
        display_name="Personal Free",
        product_codes=(PRODUCT_CHATLAB,),
        limit_values={
            LIMIT_MONTHLY_RUNS: 10,
            LIMIT_MONTHLY_AI_MESSAGES: 200,
            LIMIT_IMAGE_GENERATIONS: 10,
        },
    ),
    PLAN_PERSONAL_PLUS: PlanDefinition(
        code=PLAN_PERSONAL_PLUS,
        display_name="Personal Plus",
        product_codes=(PRODUCT_CHATLAB,),
        feature_codes=(FEATURE_EXPORTS, FEATURE_ADVANCED_CASES),
        limit_values={
            LIMIT_MONTHLY_RUNS: 200,
            LIMIT_MONTHLY_AI_MESSAGES: 5000,
            LIMIT_IMAGE_GENERATIONS: 100,
        },
    ),
    PLAN_PERSONAL_PRO: PlanDefinition(
        code=PLAN_PERSONAL_PRO,
        display_name="Personal Pro",
        product_codes=(PRODUCT_CHATLAB, PRODUCT_TRAINERLAB),
        feature_codes=(FEATURE_EXPORTS, FEATURE_ANALYTICS, FEATURE_ADVANCED_CASES, FEATURE_INSTRUCTOR_TOOLS),
        limit_values={
            LIMIT_MONTHLY_RUNS: 1000,
            LIMIT_MONTHLY_AI_MESSAGES: 20000,
            LIMIT_IMAGE_GENERATIONS: 500,
        },
    ),
}


def get_plan_definition(plan_code: str) -> PlanDefinition:
    try:
        return PLANS[plan_code]
    except KeyError as exc:
        raise KeyError(f"Unknown plan code: {plan_code}") from exc


def iter_plan_grants(plan_code: str):
    plan = get_plan_definition(plan_code)
    for product_code in plan.product_codes:
        yield {
            "product_code": product_code,
            "feature_code": "",
            "limit_code": "",
            "limit_value": None,
        }
    for feature_code in plan.feature_codes:
        feature = FEATURES[feature_code]
        yield {
            "product_code": feature.product_code,
            "feature_code": feature.code,
            "limit_code": "",
            "limit_value": None,
        }
    for limit_code, limit_value in plan.limit_values.items():
        limit = LIMITS[limit_code]
        yield {
            "product_code": limit.product_code,
            "feature_code": "",
            "limit_code": limit.code,
            "limit_value": limit_value,
        }
