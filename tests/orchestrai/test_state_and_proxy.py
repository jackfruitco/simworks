import asyncio
import types

import pytest

from orchestrai import OrchestrAI, current_app, get_current_app
from orchestrai._state import push_current_app
from orchestrai.registry.simple import Registry
from orchestrai.utils.proxy import Proxy, maybe_evaluate


def test_push_current_app_restores_previous():
    original = get_current_app()
    new_app = OrchestrAI("temp")
    with push_current_app(new_app) as active:
        assert active is new_app
        assert get_current_app() is new_app
    assert get_current_app() is original


def test_proxy_delegates_attributes_and_call():
    target = types.SimpleNamespace(value=5)

    proxy = Proxy(lambda: target)
    assert proxy.value == 5

    target.func_calls = 0

    def func(x):
        target.func_calls += x
        return target.func_calls

    target.func = func

    assert proxy.func(3) == 3
    assert maybe_evaluate(proxy) is target


def test_registry_freeze_blocks_registration():
    reg = Registry()
    reg.register("one", 1)
    reg.freeze()

    with pytest.raises(RuntimeError):
        reg.register("two", 2)


def test_registry_try_get_returns_none_for_missing_key():
    reg = Registry()

    assert reg.try_get("missing") is None


def test_registry_atry_get_returns_none_for_missing_key():
    reg = Registry()

    assert asyncio.run(reg.atry_get("missing")) is None
