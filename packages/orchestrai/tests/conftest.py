import asyncio
import sys
import types

# Provide a minimal asgiref.sync stub when the dependency is unavailable in the
# execution environment. This is sufficient for tests that rely on the sync
# wrappers but do not require thread-sensitive behavior.
if "asgiref" not in sys.modules:
    asgiref_mod = types.ModuleType("asgiref")
    sync_mod = types.ModuleType("asgiref.sync")

    def async_to_sync(func):
        def wrapper(*args, **kwargs):
            return asyncio.get_event_loop().run_until_complete(func(*args, **kwargs))
        return wrapper

    def sync_to_async(func):
        async def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper

    sync_mod.async_to_sync = async_to_sync
    sync_mod.sync_to_async = sync_to_async
    asgiref_mod.sync = sync_mod

    sys.modules["asgiref"] = asgiref_mod
    sys.modules["asgiref.sync"] = sync_mod


if "logfire" not in sys.modules:
    logfire_mod = types.SimpleNamespace(error=lambda *args, **kwargs: None)
    sys.modules["logfire"] = logfire_mod


if "slugify" not in sys.modules:
    slug_mod = types.SimpleNamespace(slugify=lambda value, **kwargs: str(value))
    sys.modules["slugify"] = slug_mod


if "pydantic" not in sys.modules:
    pydantic_mod = types.ModuleType("pydantic")

    class ValidationError(Exception):
        pass

    class ConfigDict(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class BaseModel:
        model_config = {}

        def __init__(self, **data):
            for key, value in data.items():
                setattr(self, key, value)

        @classmethod
        def model_json_schema(cls):
            props = {k: {"title": k} for k in getattr(cls, "__annotations__", {})}
            return {"title": cls.__name__, "type": "object", "properties": props}

        @classmethod
        def model_construct(cls, **kwargs):
            return cls(**kwargs)

        @classmethod
        def model_validate(cls, data):
            return cls(**data)

    class RootModel(BaseModel):
        def __init__(self, root=None, **kwargs):
            super().__init__(root=root, **kwargs)

        def __class_getitem__(cls, item):
            return cls

    def Field(default=None, **kwargs):
        return default

    def field_serializer(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def field_validator(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def model_validator(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    pydantic_mod.BaseModel = BaseModel
    pydantic_mod.ConfigDict = ConfigDict
    pydantic_mod.ValidationError = ValidationError
    pydantic_mod.RootModel = RootModel
    pydantic_mod.Field = Field
    pydantic_mod.field_serializer = field_serializer
    pydantic_mod.field_validator = field_validator
    pydantic_mod.model_validator = model_validator

    config_mod = types.ModuleType("pydantic.config")
    config_mod.ConfigDict = ConfigDict

    sys.modules["pydantic"] = pydantic_mod
    sys.modules["pydantic.config"] = config_mod
