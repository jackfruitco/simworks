import sys

from orchestrai import OrchestrAI
from orchestrai.conf.defaults import DEFAULTS
from orchestrai.loaders.default import DefaultLoader
from orchestrai.registry import singletons


def test_default_discovery_paths_include_contrib_and_patterns():
    discovery_paths = DEFAULTS["DISCOVERY_PATHS"]
    expected = [
        "orchestrai.contrib.provider_backends",
        "orchestrai.contrib.provider_codecs",
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

    assert imported == ["demo_pkg.orca.services"]
    assert sys.modules["demo_pkg.orca.services"].IMPORTED is True


def test_default_loader_imports_contrib_codecs(monkeypatch):
    # Ensure global registry starts clean for this assertion.
    singletons.codecs.clear()

    # Remove contrib modules to force the loader to import them.
    for module_name in list(sys.modules):
        if module_name.startswith("orchestrai.contrib.provider_codecs"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    app = OrchestrAI()
    app.start()

    codec_labels = app.codecs.all()
    assert "openai.responses.json" in codec_labels
