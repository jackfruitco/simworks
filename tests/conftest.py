"""Test configuration helpers for the SimWorks workspace.

This module keeps the test environment intentionally lightweight by
providing minimal stand-ins for optional third-party integrations.  The
real project depends on Django, Celery and OpenTelemetry, but the kata
environment only needs enough behaviour to import the packages under
test and exercise their logic.

The helpers below install tiny stub modules into ``sys.modules`` so that
modules such as ``simcore_ai_django.health`` and ``simcore_ai`` can be
imported without pulling in heavy external dependencies.  Only the
attributes that are touched in the tests are implemented.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = ROOT / "packages"

# Ensure the workspace packages are importable without installing them as
# editable installs.
for rel_path in ("simcore_ai/src", "simcore_ai_django/src"):
    pkg_path = PKG_ROOT / rel_path
    if str(pkg_path) not in sys.path:
        sys.path.insert(0, str(pkg_path))


def _ensure_module(name: str) -> ModuleType:
    """Return a module from ``sys.modules`` creating a blank one if needed."""

    module = sys.modules.get(name)
    if module is None:
        module = ModuleType(name)
        sys.modules[name] = module
    return module


# ---------------------------------------------------------------------------
# Minimal Django shims
# ---------------------------------------------------------------------------

django_mod = _ensure_module("django")

# django.conf.settings replacement (mutable namespace patched per test)
conf_mod = _ensure_module("django.conf")
conf_mod.settings = SimpleNamespace()
django_mod.conf = conf_mod

# django.apps.AppConfig base class used by simcore_ai_django.apps
apps_mod = _ensure_module("django.apps")


class _FakeAppConfig:
    def __init__(self, app_name: str = "", app_module: ModuleType | None = None) -> None:
        self.name = app_name or getattr(self, "name", "")
        self.app_module = app_module

    def ready(self) -> None:  # pragma: no cover - simple stub
        return None


apps_mod.AppConfig = _FakeAppConfig
apps_registry = SimpleNamespace(app_configs={})
apps_registry.get_app_config = lambda label: apps_registry.app_configs[label]
apps_registry.get_app_configs = lambda: list(apps_registry.app_configs.values())
apps_mod.apps = apps_registry
django_mod.apps = apps_mod

# django.utils.module_loading.autodiscover_modules stub used during AppConfig.ready
utils_mod = _ensure_module("django.utils")
module_loading_mod = _ensure_module("django.utils.module_loading")


def autodiscover_modules(*_modules: str, **_kwargs: object) -> None:  # pragma: no cover - trivial
    return None


module_loading_mod.autodiscover_modules = autodiscover_modules
utils_mod.module_loading = module_loading_mod
django_mod.utils = utils_mod

# django.dispatch.Signal used by simcore_ai_django.signals
dispatch_mod = _ensure_module("django.dispatch")


class _Signal:
    """Minimal drop-in replacement for :class:`django.dispatch.Signal`."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self._receivers: list = []

    def connect(self, receiver, **_kwargs: object) -> None:  # pragma: no cover - unused hook
        self._receivers.append(receiver)

    def send_robust(self, sender=None, **payload: object):  # pragma: no cover - behaviour trivial
        results = []
        for receiver in list(self._receivers):
            try:
                results.append((receiver, receiver(sender=sender, **payload)))
            except Exception as exc:  # pragma: no cover - defensive
                results.append((receiver, exc))
        return results


dispatch_mod.Signal = _Signal
django_mod.dispatch = dispatch_mod


# ---------------------------------------------------------------------------
# Celery stub – provides a ``shared_task`` decorator returning a callable
# object with ``apply_async`` so execution backends can be imported.
# ---------------------------------------------------------------------------

celery_mod = _ensure_module("celery")


class _CeleryTask:
    def __init__(self, func):
        self._func = func

    def __call__(self, *args, **kwargs):  # pragma: no cover - unused in tests
        return self._func(*args, **kwargs)

    def apply_async(self, args=None, kwargs=None, queue=None, eta=None, countdown=None, priority=None):
        # Match the shape expected by tests (a simple object with an ``id`` attribute).
        return SimpleNamespace(
            id="test-task",
            args=args,
            kwargs=kwargs,
            queue=queue,
            eta=eta,
            countdown=countdown,
            priority=priority,
        )


def shared_task(*_task_args: object, **_task_kwargs: object):
    def decorator(func):
        return _CeleryTask(func)

    return decorator


celery_mod.shared_task = shared_task


@pytest.fixture
def settings(monkeypatch):
    settings_ns = SimpleNamespace()
    monkeypatch.setattr(conf_mod, "settings", settings_ns, raising=False)
    return settings_ns


# ---------------------------------------------------------------------------
# OpenTelemetry stub – implements the handful of symbols referenced by the
# tracing helpers.  The implementations keep enough surface to allow spans
# to be entered without raising errors during tests.
# ---------------------------------------------------------------------------

otel_mod = _ensure_module("opentelemetry")
trace_mod = _ensure_module("opentelemetry.trace")


class _Span:
    def __init__(self) -> None:
        self.attributes = {}

    def set_attribute(self, key, value):  # pragma: no cover - trivial
        self.attributes[key] = value

    def record_exception(self, exc):  # pragma: no cover - trivial
        self.attributes.setdefault("exceptions", []).append(exc)

    def set_status(self, status):  # pragma: no cover - trivial
        self.attributes["status"] = status


class _Tracer:
    def start_as_current_span(self, _name, kind=None):  # pragma: no cover - trivial
        span = _Span()

        class _Manager:
            def __enter__(self_nonlocal):
                return span

            def __exit__(self_nonlocal, exc_type, exc, tb):
                return False

        return _Manager()


class _SpanKind:
    INTERNAL = "INTERNAL"


class _StatusCode:
    ERROR = "ERROR"


class _Status:
    def __init__(self, status_code, description=None):  # pragma: no cover - trivial
        self.status_code = status_code
        self.description = description


def _get_tracer(_name=None):  # pragma: no cover - trivial helper
    return _Tracer()


def _noop(*_args, **_kwargs):  # pragma: no cover - defensive helper
    return None


trace_mod.get_tracer = _get_tracer
trace_mod.Span = _Span
trace_mod.SpanKind = _SpanKind
trace_mod.Status = _Status
trace_mod.StatusCode = _StatusCode
trace_mod.Tracer = _Tracer
trace_mod.SpanContext = object  # type: ignore[attr-defined]
trace_mod.Link = object  # type: ignore[attr-defined]
trace_mod.set_tracer_provider = _noop
trace_mod.get_tracer_provider = _noop

otel_mod.trace = trace_mod

propagation_pkg = _ensure_module("opentelemetry.trace.propagation")
tracecontext_mod = _ensure_module("opentelemetry.trace.propagation.tracecontext")


class TraceContextTextMapPropagator:  # pragma: no cover - trivial helper
    def inject(self, carrier):
        carrier["traceparent"] = carrier.get("traceparent", "00-test-trace")

    def extract(self, carrier):
        return carrier.get("traceparent")


tracecontext_mod.TraceContextTextMapPropagator = TraceContextTextMapPropagator
propagation_pkg.tracecontext = tracecontext_mod

# ---------------------------------------------------------------------------
# Pydantic shim – enough surface for the models imported by simcore_ai.
# ---------------------------------------------------------------------------

pydantic_mod = _ensure_module("pydantic")


class _BaseModel:
    def __init__(self, **data):  # pragma: no cover - trivial
        for key, value in data.items():
            setattr(self, key, value)

    def model_dump(self):  # pragma: no cover - trivial
        return self.__dict__.copy()


class _ValidationError(Exception):  # pragma: no cover - trivial
    pass


def _field(default=None, **_kwargs):  # pragma: no cover - trivial helper
    return default


pydantic_mod.BaseModel = _BaseModel
pydantic_mod.ConfigDict = dict  # type: ignore[assignment]
pydantic_mod.ValidationError = _ValidationError
pydantic_mod.Field = _field


def _create_model(name: str, **fields):  # pragma: no cover - best-effort shim
    attrs = {}
    for key, value in fields.items():
        if isinstance(value, tuple) and value:
            attrs[key] = value[1]
        else:
            attrs[key] = value
    return type(name, (_BaseModel,), attrs)


pydantic_mod.create_model = _create_model


config_mod = _ensure_module("pydantic.config")
config_mod.ConfigDict = dict  # type: ignore[assignment]


db_mod = _ensure_module("django.db")


class _Atomic:
    def __enter__(self):  # pragma: no cover - trivial
        return None

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - trivial
        return False


class _Transaction:
    def atomic(self):  # pragma: no cover - trivial
        return _Atomic()


db_mod.transaction = _Transaction()


models_mod = _ensure_module("django.db.models")


class _Model:
    objects = SimpleNamespace()

    def save(self, *args, **kwargs):  # pragma: no cover - trivial
        return None


class _Field:
    def __init__(self, *args, **kwargs):  # pragma: no cover - trivial
        self.args = args
        self.kwargs = kwargs


def _ForeignKey(to, *args, **kwargs):  # pragma: no cover - trivial
    return _Field(to, *args, **kwargs)


class _Index:
    def __init__(self, *args, **kwargs):  # pragma: no cover - trivial
        self.args = args
        self.kwargs = kwargs


models_mod.Model = _Model
models_mod.DateTimeField = _Field
models_mod.CharField = _Field
models_mod.BooleanField = _Field
models_mod.JSONField = _Field
models_mod.UUIDField = _Field
models_mod.IntegerField = _Field
models_mod.TextField = _Field
models_mod.PositiveIntegerField = _Field
models_mod.ForeignKey = _ForeignKey
models_mod.Index = _Index
models_mod.SET_NULL = object()

# django.utils.timezone stub
timezone_mod = _ensure_module("django.utils.timezone")


def _now():  # pragma: no cover - trivial helper
    import datetime

    return datetime.datetime.utcnow()


timezone_mod.now = _now

django_mod.utils.timezone = timezone_mod

