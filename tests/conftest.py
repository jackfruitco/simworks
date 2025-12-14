import sys
import types
import json
import asyncio

# ----------------------- pydantic stub -----------------------
class _FieldInfo:
    def __init__(self, default=... , default_factory=None, repr=True, **kwargs):
        self.default = default
        self.default_factory = default_factory
        self.repr = repr
        self.metadata = kwargs


def Field(*, default=... , default_factory=None, repr=True, **kwargs):
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


asgiref_sync.sync_to_async = sync_to_async
sys.modules.setdefault("asgiref.sync", asgiref_sync)
asgiref = types.ModuleType("asgiref")
asgiref.sync = asgiref_sync
sys.modules.setdefault("asgiref", asgiref)

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
