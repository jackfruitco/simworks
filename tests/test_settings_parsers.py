"""Tests for config/settings_parsers.py env-var helpers."""

import importlib.util
from pathlib import Path

import pytest

# Load settings_parsers directly to avoid triggering config/__init__.py (Celery init).
_parsers_path = Path(__file__).resolve().parents[1] / "SimWorks" / "config" / "settings_parsers.py"
_spec = importlib.util.spec_from_file_location("settings_parsers", _parsers_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

int_from_env = _mod.int_from_env
optional_int_from_env = _mod.optional_int_from_env
str_from_env = _mod.str_from_env
optional_str_from_env = _mod.optional_str_from_env


class TestIntFromEnv:
    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("_TEST_INT", raising=False)
        assert int_from_env("_TEST_INT", default=42) == 42

    def test_blank_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("_TEST_INT", "")
        assert int_from_env("_TEST_INT", default=42) == 42

    def test_whitespace_only_returns_default(self, monkeypatch):
        monkeypatch.setenv("_TEST_INT", "   ")
        assert int_from_env("_TEST_INT", default=42) == 42

    def test_valid_integer(self, monkeypatch):
        monkeypatch.setenv("_TEST_INT", "7")
        assert int_from_env("_TEST_INT", default=0) == 7

    def test_junk_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("_TEST_INT", "abc")
        with pytest.raises(ValueError, match="_TEST_INT"):
            int_from_env("_TEST_INT", default=0)

    def test_minimum_enforced(self, monkeypatch):
        monkeypatch.setenv("_TEST_INT", "0")
        with pytest.raises(ValueError, match="_TEST_INT"):
            int_from_env("_TEST_INT", default=0, minimum=1)

    def test_minimum_not_violated(self, monkeypatch):
        monkeypatch.setenv("_TEST_INT", "5")
        assert int_from_env("_TEST_INT", default=0, minimum=1) == 5


class TestStrFromEnv:
    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("_TEST_STR", raising=False)
        assert str_from_env("_TEST_STR", "fallback") == "fallback"

    def test_blank_string_returns_default(self, monkeypatch):
        # Compose interpolates unset variables to an empty string.
        monkeypatch.setenv("_TEST_STR", "")
        assert str_from_env("_TEST_STR", "fallback") == "fallback"

    def test_whitespace_only_returns_default(self, monkeypatch):
        monkeypatch.setenv("_TEST_STR", "   ")
        assert str_from_env("_TEST_STR", "fallback") == "fallback"

    def test_value_is_stripped(self, monkeypatch):
        monkeypatch.setenv("_TEST_STR", "  gpt-realtime  ")
        assert str_from_env("_TEST_STR", "fallback") == "gpt-realtime"


class TestOptionalStrFromEnv:
    def test_missing_returns_none(self, monkeypatch):
        monkeypatch.delenv("_TEST_OPT_STR", raising=False)
        assert optional_str_from_env("_TEST_OPT_STR") is None

    def test_blank_string_returns_none(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_STR", "")
        assert optional_str_from_env("_TEST_OPT_STR") is None

    def test_whitespace_only_returns_none(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_STR", "   ")
        assert optional_str_from_env("_TEST_OPT_STR") is None

    def test_value_is_stripped(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_STR", " sk-test ")
        assert optional_str_from_env("_TEST_OPT_STR") == "sk-test"


class TestOptionalIntFromEnv:
    def test_missing_returns_none(self, monkeypatch):
        monkeypatch.delenv("_TEST_OPT_INT", raising=False)
        assert optional_int_from_env("_TEST_OPT_INT") is None

    def test_blank_string_returns_none(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_INT", "")
        assert optional_int_from_env("_TEST_OPT_INT") is None

    def test_whitespace_only_returns_none(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_INT", "   ")
        assert optional_int_from_env("_TEST_OPT_INT") is None

    def test_valid_integer(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_INT", "256")
        assert optional_int_from_env("_TEST_OPT_INT") == 256

    def test_junk_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_INT", "abc")
        with pytest.raises(ValueError, match="_TEST_OPT_INT"):
            optional_int_from_env("_TEST_OPT_INT")

    def test_minimum_enforced(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_INT", "64")
        with pytest.raises(ValueError, match="_TEST_OPT_INT"):
            optional_int_from_env("_TEST_OPT_INT", minimum=128)

    def test_minimum_not_violated(self, monkeypatch):
        monkeypatch.setenv("_TEST_OPT_INT", "128")
        assert optional_int_from_env("_TEST_OPT_INT", minimum=128) == 128
