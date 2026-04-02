"""Centralized guard policy resolver.

All guard thresholds and limits are defined here — not scattered across
endpoints or service functions.  The resolver is a pure lookup table driven
by (lab_type, product_code) pairs with sensible defaults.

Product code for a session is resolved from the simulation's account + user
entitlements via ``apps.billing.services.entitlements``.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.billing.catalog import ProductCode

from .enums import LabType


@dataclass(frozen=True)
class GuardPolicy:
    """Immutable policy bag returned by the resolver.

    Every threshold is configurable per lab x product.  ``None`` means
    "unlimited / not applicable".
    """

    # ── Inactivity (seconds) ────────────────────────────────────────────
    inactivity_warning_seconds: int = 270  # 4 m 30 s
    inactivity_pause_seconds: int = 300  # 5 m
    heartbeat_interval_seconds: int = 15
    heartbeat_stale_seconds: int = 45

    # ── Runtime cap (active seconds) ────────────────────────────────────
    runtime_cap_seconds: int | None = None  # None = unlimited

    # ── Wall-clock expiry ───────────────────────────────────────────────
    wall_clock_expiry_seconds: int | None = 7200  # 2 h default

    # ── Token limits ────────────────────────────────────────────────────
    session_token_limit: int | None = None
    user_token_limit: int | None = None
    account_token_limit: int | None = None

    # ── TrainerLab pre-session admission ────────────────────────────────
    pre_session_init_reserve_tokens: int = 50_000
    pre_session_safety_reserve_tokens: int = 10_000

    # ── ChatLab send thresholds ─────────────────────────────────────────
    chat_send_min_safe_tokens: int = 5_000
    chat_warning_threshold_tokens: int = 20_000

    # ── Derived helpers ─────────────────────────────────────────────────

    @property
    def pre_session_total_reserve(self) -> int:
        return self.pre_session_init_reserve_tokens + self.pre_session_safety_reserve_tokens

    @property
    def has_runtime_cap(self) -> bool:
        return self.runtime_cap_seconds is not None

    @property
    def has_wall_clock_expiry(self) -> bool:
        return self.wall_clock_expiry_seconds is not None


# ── Default policy (fallback when no product-specific override exists) ──

_DEFAULT = GuardPolicy()


# ── Policy table keyed by (lab_type, product_code) ──────────────────────
#
# Only entries that *differ* from the default need to be listed.

_POLICY_TABLE: dict[tuple[str, str], GuardPolicy] = {
    # TrainerLab plans
    (LabType.TRAINERLAB, ProductCode.TRAINERLAB_GO): GuardPolicy(
        runtime_cap_seconds=1200,  # 20 min
    ),
    (LabType.TRAINERLAB, ProductCode.TRAINERLAB_PLUS): GuardPolicy(
        runtime_cap_seconds=1800,  # 30 min
    ),
    (LabType.TRAINERLAB, ProductCode.MEDSIM_ONE): GuardPolicy(
        runtime_cap_seconds=1200,  # 20 min
    ),
    (LabType.TRAINERLAB, ProductCode.MEDSIM_ONE_PLUS): GuardPolicy(
        runtime_cap_seconds=2700,  # 45 min
    ),
    # ChatLab plans
    (LabType.CHATLAB, ProductCode.CHATLAB_GO): GuardPolicy(
        runtime_cap_seconds=1200,  # 20 min
        # ChatLab doesn't use inactivity autopause by default.
        inactivity_warning_seconds=0,
        inactivity_pause_seconds=0,
    ),
    (LabType.CHATLAB, ProductCode.CHATLAB_PLUS): GuardPolicy(
        runtime_cap_seconds=1800,  # 30 min
        inactivity_warning_seconds=0,
        inactivity_pause_seconds=0,
    ),
    (LabType.CHATLAB, ProductCode.MEDSIM_ONE): GuardPolicy(
        runtime_cap_seconds=1200,  # 20 min
        inactivity_warning_seconds=0,
        inactivity_pause_seconds=0,
    ),
    (LabType.CHATLAB, ProductCode.MEDSIM_ONE_PLUS): GuardPolicy(
        runtime_cap_seconds=2700,  # 45 min
        inactivity_warning_seconds=0,
        inactivity_pause_seconds=0,
    ),
}


def resolve_policy(lab_type: str, product_code: str) -> GuardPolicy:
    """Return the guard policy for a given lab type and product code.

    Falls back to ``_DEFAULT`` when no product-specific policy exists.
    """
    return _POLICY_TABLE.get((lab_type, product_code), _DEFAULT)


def resolve_policy_for_simulation(simulation) -> tuple[str, str, GuardPolicy]:
    """Resolve lab type, product code, and policy from a Simulation instance.

    Determines the lab type by checking which session type exists, then
    resolves the best matching product code from the user's entitlements.

    Returns (lab_type, product_code, policy).
    """
    lab_type = _detect_lab_type(simulation)
    product_code = _resolve_product_code(simulation, lab_type)
    policy = resolve_policy(lab_type, product_code)
    return lab_type, product_code, policy


def _detect_lab_type(simulation) -> str:
    """Detect which lab a simulation belongs to."""
    if hasattr(simulation, "trainerlab_session"):
        return LabType.TRAINERLAB
    return LabType.CHATLAB


def _resolve_product_code(simulation, lab_type: str) -> str:
    """Resolve the best product code for this simulation's user + account."""
    from apps.billing.catalog import product_codes_for_lab
    from apps.billing.services.entitlements import get_effective_entitlements

    user = simulation.user
    account = simulation.account
    if not user or not account:
        return ""

    lab_products = set(product_codes_for_lab(lab_type))
    if not lab_products:
        return ""

    for ent in get_effective_entitlements(user, account):
        code = ent.product_code or ""
        if code in lab_products:
            return code
    return ""
