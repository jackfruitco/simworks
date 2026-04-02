"""Tests for the guard policy resolver."""

from __future__ import annotations

import pytest

from apps.billing.catalog import ProductCode
from apps.guards.enums import LabType
from apps.guards.policy import GuardPolicy, resolve_policy


class TestGuardPolicyDefaults:
    """Verify default policy values."""

    def test_default_inactivity_thresholds(self):
        policy = GuardPolicy()
        assert policy.inactivity_warning_seconds == 270
        assert policy.inactivity_pause_seconds == 300
        assert policy.heartbeat_interval_seconds == 15
        assert policy.heartbeat_stale_seconds == 45

    def test_default_has_no_runtime_cap(self):
        policy = GuardPolicy()
        assert policy.runtime_cap_seconds is None
        assert not policy.has_runtime_cap

    def test_default_wall_clock_expiry(self):
        policy = GuardPolicy()
        assert policy.wall_clock_expiry_seconds == 7200
        assert policy.has_wall_clock_expiry

    def test_default_pre_session_reserve(self):
        policy = GuardPolicy()
        assert policy.pre_session_total_reserve == 60_000

    def test_default_chat_thresholds(self):
        policy = GuardPolicy()
        assert policy.chat_send_min_safe_tokens == 5_000
        assert policy.chat_warning_threshold_tokens == 20_000


class TestResolvePolicy:
    """Verify plan-based policy resolution."""

    def test_trainerlab_go_runtime_cap(self):
        policy = resolve_policy(LabType.TRAINERLAB, ProductCode.TRAINERLAB_GO)
        assert policy.runtime_cap_seconds == 1200  # 20 min

    def test_trainerlab_plus_runtime_cap(self):
        policy = resolve_policy(LabType.TRAINERLAB, ProductCode.TRAINERLAB_PLUS)
        assert policy.runtime_cap_seconds == 1800  # 30 min

    def test_medsim_one_plus_runtime_cap(self):
        policy = resolve_policy(LabType.TRAINERLAB, ProductCode.MEDSIM_ONE_PLUS)
        assert policy.runtime_cap_seconds == 2700  # 45 min

    def test_chatlab_go_runtime_cap(self):
        policy = resolve_policy(LabType.CHATLAB, ProductCode.CHATLAB_GO)
        assert policy.runtime_cap_seconds == 1200

    def test_chatlab_go_no_inactivity_pause(self):
        """ChatLab does not use inactivity autopause by default."""
        policy = resolve_policy(LabType.CHATLAB, ProductCode.CHATLAB_GO)
        assert policy.inactivity_warning_seconds == 0
        assert policy.inactivity_pause_seconds == 0

    def test_trainerlab_has_inactivity_pause(self):
        policy = resolve_policy(LabType.TRAINERLAB, ProductCode.TRAINERLAB_GO)
        assert policy.inactivity_warning_seconds == 270
        assert policy.inactivity_pause_seconds == 300

    def test_unknown_product_returns_default(self):
        policy = resolve_policy(LabType.TRAINERLAB, "unknown_product")
        assert policy.runtime_cap_seconds is None

    def test_policies_vary_by_lab_and_product(self):
        tl_go = resolve_policy(LabType.TRAINERLAB, ProductCode.TRAINERLAB_GO)
        tl_plus = resolve_policy(LabType.TRAINERLAB, ProductCode.TRAINERLAB_PLUS)
        cl_go = resolve_policy(LabType.CHATLAB, ProductCode.CHATLAB_GO)

        assert tl_go.runtime_cap_seconds != tl_plus.runtime_cap_seconds
        assert tl_go.inactivity_pause_seconds != cl_go.inactivity_pause_seconds

    def test_policy_is_frozen(self):
        policy = resolve_policy(LabType.TRAINERLAB, ProductCode.TRAINERLAB_GO)
        with pytest.raises(AttributeError):
            policy.runtime_cap_seconds = 999
