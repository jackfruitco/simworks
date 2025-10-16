import importlib
import types
import pytest


def test_settings_defaults_when_missing(settings, monkeypatch):
    # No AI_EXECUTION_BACKENDS defined → hard defaults used
    if hasattr(settings, "AI_EXECUTION_BACKENDS"):
        delattr(settings, "AI_EXECUTION_BACKENDS")
    import simcore_ai_django.execution.helpers as h
    importlib.reload(h)
    assert h.settings_default_backend() == "immediate"
    assert h.settings_default_mode() == "sync"
    assert h.settings_default_queue_name() is None

def test_settings_case_insensitivity(settings):
    settings.AI_EXECUTION_BACKENDS = {"DEFAULT_BACKEND": "IMMEDIATE", "DEFAULT_MODE": "ASYNC"}
    import simcore_ai_django.execution.helpers as h
    importlib.reload(h)
    assert h.settings_default_backend() == "immediate"
    assert h.settings_default_mode() == "async"

def test_settings_queue_default_present(settings):
    settings.AI_EXECUTION_BACKENDS = {
        "DEFAULT_BACKEND": "celery",
        "DEFAULT_MODE": "sync",
        "CELERY": {"queue_default": "ai-q"},
    }
    import simcore_ai_django.execution.helpers as h
    importlib.reload(h)
    assert h.settings_default_queue_name() == "ai-q"