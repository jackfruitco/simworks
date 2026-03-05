import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
import types

import pytest


# ----------------------- pydantic stub -----------------------
class _FieldInfo:
    def __init__(self, default=..., default_factory=None, repr=True, **kwargs):
        self.default = default
        self.default_factory = default_factory
        self.repr = repr
        self.metadata = kwargs


def Field(*args, default=..., default_factory=None, repr=True, **kwargs):
    return _FieldInfo(default, default_factory, repr=repr, **kwargs)


class ValidationError(Exception):
    pass


class ConfigDict(dict):
    pass


class BaseModel:
    model_config = ConfigDict()

    def __init__(self, **data):
        cls = self.__class__
        for name, value in cls.__dict__.items():
            if name.startswith("__"):
                continue
            if isinstance(value, _FieldInfo):
                if name in data:
                    setattr(self, name, data.pop(name))
                elif value.default_factory is not None:
                    setattr(self, name, value.default_factory())
                elif value.default is not ...:
                    setattr(self, name, value.default)
            elif not callable(value):
                if name in data:
                    setattr(self, name, data.pop(name))
                else:
                    setattr(self, name, value)
        for key, val in data.items():
            setattr(self, key, val)

    @classmethod
    def model_validate(cls, data):
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("model_validate expects dict or instance")
        return cls(**data)

    @classmethod
    def model_construct(cls, **kwargs):
        obj = cls.__new__(cls)
        for k, v in kwargs.items():
            setattr(obj, k, v)
        return obj

    def model_dump(self, include=None, exclude_none=False, **_: object):
        result = {}
        for key, value in self.__dict__.items():
            if include is not None and key not in include:
                continue
            if exclude_none and value is None:
                continue
            result[key] = value
        return result

    def model_dump_json(self, **kwargs):
        return json.dumps(self.model_dump(**kwargs))

    @classmethod
    def model_json_schema(cls):
        props = {name: {"type": "string"} for name in getattr(cls, "__annotations__", {})}
        for name, value in cls.__dict__.items():
            if isinstance(value, _FieldInfo):
                props[name] = {"type": "string"}
        return {"type": "object", "properties": props}


class RootModel(BaseModel):
    def __init__(self, root=None, **kwargs):
        super().__init__(**kwargs)
        self.root = root

    def model_dump(self, *args, **kwargs):
        data = super().model_dump(*args, **kwargs)
        data["root"] = getattr(self, "root", None)
        return data

    @classmethod
    def __class_getitem__(cls, _item):
        return cls


def field_validator(*_args, **_kwargs):
    def decorator(fn):
        return fn

    return decorator


def model_validator(*_args, **_kwargs):
    def decorator(fn):
        return fn

    return decorator


def field_serializer(*_args, **_kwargs):
    def decorator(fn):
        return fn

    return decorator


class SecretStr(str):
    def get_secret_value(self):
        return str(self)


class HttpUrl(str):
    pass


pydantic = types.ModuleType("pydantic")
pydantic.Field = Field
pydantic.BaseModel = BaseModel
pydantic.ValidationError = ValidationError
pydantic.ConfigDict = ConfigDict
pydantic.RootModel = RootModel
pydantic.field_validator = field_validator
pydantic.model_validator = model_validator
pydantic.field_serializer = field_serializer
pydantic.SecretStr = SecretStr
pydantic.HttpUrl = HttpUrl
sys.modules.setdefault("pydantic", pydantic)

config = types.ModuleType("pydantic.config")
config.ConfigDict = ConfigDict
sys.modules.setdefault("pydantic.config", config)

# ----------------------- asgiref stub -----------------------
asgiref_sync = types.ModuleType("asgiref.sync")


def sync_to_async(func):
    async def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def async_to_sync(func):
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result

    return wrapper


asgiref_sync.sync_to_async = sync_to_async
asgiref_sync.async_to_sync = async_to_sync
sys.modules.setdefault("asgiref.sync", asgiref_sync)
asgiref = types.ModuleType("asgiref")
asgiref.sync = asgiref_sync
sys.modules.setdefault("asgiref", asgiref)

# ----------------------- logfire stub -----------------------
logfire = types.SimpleNamespace(error=lambda *args, **kwargs: None)
sys.modules.setdefault("logfire", logfire)


# ----------------------- slugify stub -----------------------
def _slugify(value):
    return str(value).replace(" ", "-")


slugify_module = types.SimpleNamespace(slugify=_slugify)
sys.modules.setdefault("slugify", slugify_module)


# ----------------------- opentelemetry stub -----------------------
class _Span:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def record_exception(self, err):
        self.attributes["exception"] = err


class _Status:
    def __init__(self, code, description=None):
        self.code = code
        self.description = description


class _Tracer:
    def start_as_current_span(self, name, kind=None):
        span = _Span()

        class Ctx:
            def __enter__(self_inner):
                return span

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        return Ctx()


class _TraceModule(types.SimpleNamespace):
    def get_tracer(self, name):
        return _Tracer()


opentelemetry_trace = _TraceModule()

opentelemetry = types.ModuleType("opentelemetry")
opentelemetry.trace = opentelemetry_trace
sys.modules.setdefault("opentelemetry", opentelemetry)
sys.modules.setdefault("opentelemetry.trace", opentelemetry_trace)


class StatusCode:
    ERROR = "error"


class SpanKind:
    INTERNAL = "internal"


Status = _Status
Span = _Span
Tracer = _Tracer
sys.modules.setdefault("opentelemetry.trace.Status", Status)
sys.modules.setdefault("opentelemetry.trace.StatusCode", StatusCode)
sys.modules.setdefault("opentelemetry.trace.SpanKind", SpanKind)
sys.modules.setdefault("opentelemetry.trace.Span", Span)
sys.modules.setdefault("opentelemetry.trace.Tracer", Tracer)


_LANE_MARKERS = {"unit", "component", "integration", "contract", "system", "e2e"}


class FailureArtifactCollector:
    """Per-test artifact sink used to persist failure diagnostics."""

    def __init__(self) -> None:
        self.records: dict[str, object] = {}

    def record(self, key: str, payload: object) -> None:
        self.records[key] = payload

    def capture_request(
        self,
        *,
        method: str,
        url: str,
        body: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.record(
            "request",
            {
                "method": method,
                "url": url,
                "body": body,
                "headers": headers or {},
            },
        )

    def capture_response(self, response: object) -> None:
        payload: dict[str, object] = {}
        status_code = getattr(response, "status_code", None)
        if status_code is not None:
            payload["status_code"] = int(status_code)
        headers = getattr(response, "headers", None)
        if headers is not None:
            payload["headers"] = dict(headers)
        data = None
        if hasattr(response, "json"):
            try:
                data = response.json()
            except Exception:
                data = None
        if data is None and hasattr(response, "content"):
            try:
                data = getattr(response, "content", b"")
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode("utf-8", errors="replace")
            except Exception:
                data = None
        if data is not None:
            payload["body"] = data
        self.record("response", payload)


def _has_lane_marker(item: pytest.Item) -> bool:
    return any(item.get_closest_marker(marker) for marker in _LANE_MARKERS)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        path = str(getattr(item, "path", getattr(item, "fspath", "")))
        if (
            "packages/orchestrai/tests/" in path or "packages/orchestrai_django/tests/" in path
        ) and not item.get_closest_marker("contract"):
            item.add_marker(pytest.mark.contract)
        if item.get_closest_marker("django_db"):
            if not item.get_closest_marker("integration"):
                item.add_marker(pytest.mark.integration)
            continue
        if not _has_lane_marker(item):
            item.add_marker(pytest.mark.unit)


@pytest.fixture
def failure_artifacts(request: pytest.FixtureRequest) -> FailureArtifactCollector:
    collector = FailureArtifactCollector()
    request.node._failure_artifacts = collector
    return collector


def _collect_db_counts() -> dict[str, int]:
    try:
        from django.apps import apps
    except Exception:
        return {}
    labels = (
        "simcore.Simulation",
        "chatlab.Message",
        "common.OutboxEvent",
        "orchestrai_django.ServiceCall",
    )
    counts: dict[str, int] = {}
    for label in labels:
        try:
            model = apps.get_model(label)
            if model is not None:
                counts[label] = model.objects.count()
        except Exception:
            continue
    return counts


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or report.passed:
        return

    collector = getattr(item, "_failure_artifacts", None)
    if collector is None:
        collector = FailureArtifactCollector()
        item._failure_artifacts = collector

    marker_names = sorted(mark.name for mark in item.iter_markers())
    collector.record("markers", marker_names)
    if item.get_closest_marker("django_db"):
        db_counts = _collect_db_counts()
        if db_counts:
            collector.record("db_counts", db_counts)

    artifact_dir = Path(os.environ.get("PYTEST_FAILURE_ARTIFACT_DIR", ".pytest-failure-artifacts"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    safe_nodeid = re.sub(r"[^A-Za-z0-9_.-]+", "_", item.nodeid)
    artifact_path = artifact_dir / f"{safe_nodeid}.json"
    payload = {
        "nodeid": item.nodeid,
        "generated_at": datetime.now(UTC).isoformat(),
        "artifacts": collector.records,
    }
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    item.user_properties.append(("failure_artifact", str(artifact_path)))
