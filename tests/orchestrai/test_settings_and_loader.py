import importlib
import os
import sys
import types

from orchestrai.conf.settings import Settings, _filter_by_namespace
from orchestrai.loaders.default import DefaultLoader


def test_filter_by_namespace():
    mapping = {"FOO": 1, "BAR": 2, "NS_X": 3, "NS_Y": 4, "lower": 5}
    assert _filter_by_namespace(mapping, None) == {"FOO": 1, "BAR": 2, "NS_X": 3, "NS_Y": 4}
    assert _filter_by_namespace(mapping, "NS") == {"X": 3, "Y": 4}


def test_settings_update_from_object_and_envvar(monkeypatch, tmp_path):
    module = types.ModuleType("temp_conf")
    module.FOO = "foo"
    module.NS_BAR = "bar"
    monkeypatch.setitem(sys.modules, "temp_conf", module)

    settings = Settings()
    settings.update_from_object("temp_conf")
    assert settings["FOO"] == "foo"

    settings.update_from_object("temp_conf", namespace="NS")
    assert settings["BAR"] == "bar"

    env_module = types.ModuleType("env_conf")
    env_module.BAZ = "baz"
    monkeypatch.setitem(sys.modules, "env_conf", env_module)
    monkeypatch.setenv("ORCHESTRAI_CONFIG_MODULE", "env_conf")

    settings.update_from_envvar()
    assert settings["BAZ"] == "baz"


def test_default_loader_autodiscover(monkeypatch, tmp_path):
    mod_name = "dummy_module"
    dummy_file = tmp_path / "dummy_module.py"
    dummy_file.write_text("VALUE=1")
    sys.path.insert(0, str(tmp_path))
    try:
        loader = DefaultLoader()
        imported = loader.autodiscover(types.SimpleNamespace(), [mod_name, ""])
        assert imported == [mod_name]
        module = importlib.import_module(mod_name)
        assert getattr(module, "VALUE", None) == 1
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(mod_name, None)
