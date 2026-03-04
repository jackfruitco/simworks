import sys

from orchestrai.conf.defaults import DEFAULTS
from orchestrai.loaders.default import DefaultLoader


def test_default_discovery_paths_include_patterns():
    discovery_paths = DEFAULTS["DISCOVERY_PATHS"]
    expected = [
        "*.orca.services",
        "*.orca.output_schemas",
        "*.orca.codecs",
        "*.ai.services",
    ]

    for path in expected:
        assert path in discovery_paths


def test_default_loader_expands_glob_patterns(monkeypatch, tmp_path):
    package_root = tmp_path / "demo_pkg"
    services_dir = package_root / "orca" / "services"
    services_dir.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "orca" / "__init__.py").write_text("", encoding="utf-8")
    (services_dir / "__init__.py").write_text("IMPORTED = True\n", encoding="utf-8")

    monkeypatch.syspath_prepend(str(tmp_path))
    for module in ("demo_pkg", "demo_pkg.orca", "demo_pkg.orca.services"):
        monkeypatch.delitem(sys.modules, module, raising=False)

    loader = DefaultLoader()
    imported = loader.autodiscover(None, ["*.orca.services", "*.missing.module"])

    assert "demo_pkg.orca.services" in imported
    assert sys.modules["demo_pkg.orca.services"].IMPORTED is True
