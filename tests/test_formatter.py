import json
import importlib.util
import sys
import types
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Stub packages to satisfy absolute imports in formatter modules without
# requiring the full Django-dependent package hierarchy.
core_pkg = types.ModuleType("core")
core_pkg.__path__ = []
sys.modules.setdefault("core", core_pkg)
core_utils_pkg = types.ModuleType("core.utils")
core_utils_pkg.__path__ = []
sys.modules.setdefault("core.utils", core_utils_pkg)
core_utils_formatters_pkg = types.ModuleType("core.utils.formatters")
core_utils_formatters_pkg.__path__ = []
sys.modules.setdefault("core.utils.formatters", core_utils_formatters_pkg)

# Stub minimal django.http.HttpResponse to satisfy base module import
django_module = types.ModuleType("django")
http_module = types.ModuleType("django.http")

class _HttpResponse(str):
    pass

http_module.HttpResponse = _HttpResponse
django_module.http = http_module
sys.modules.setdefault("django", django_module)
sys.modules.setdefault("django.http", http_module)

# Load registry module manually
registry_path = BASE_DIR / "SimWorks/core/utils/formatters/registry.py"
spec_reg = importlib.util.spec_from_file_location(
    "core.utils.formatters.registry", registry_path
)
registry_module = importlib.util.module_from_spec(spec_reg)
spec_reg.loader.exec_module(registry_module)
sys.modules["core.utils.formatters.registry"] = registry_module

# Load base module manually
base_path = BASE_DIR / "SimWorks/core/utils/formatters/base.py"
spec_base = importlib.util.spec_from_file_location(
    "core.utils.formatters.base", base_path
)
base_module = importlib.util.module_from_spec(spec_base)
spec_base.loader.exec_module(base_module)
Formatter = base_module.Formatter


@registry_module.register_formatter("json")
def _json_formatter(self, **kwargs):
    import json as _json

    return _json.dumps(self.safe_data(), **kwargs)


def test_save_returns_path_and_writes_file(tmp_path):
    data = {"foo": "bar"}
    formatter = Formatter(data)
    path = tmp_path / "out.json"
    returned_path = formatter.save("json", path=str(path), indent=2)
    assert returned_path == str(path)
    assert json.loads(path.read_text()) == [data]
