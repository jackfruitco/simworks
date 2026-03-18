import sys

from orchestrai.conf.defaults import DEFAULTS
from orchestrai.loaders.default import DefaultLoader


def test_default_discovery_paths_include_patterns():
    discovery_paths = DEFAULTS["DISCOVERY_PATHS"]
    expected = [
        "*.orca.services",
        "*.orca.instructions",
        "*.orca.output_schemas",
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


def test_default_loader_discovers_python_and_yaml_instructions(monkeypatch, tmp_path):
    package_root = tmp_path / "demo_orca_pkg"
    instructions_dir = package_root / "orca" / "instructions"
    instructions_dir.mkdir(parents=True)

    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "orca" / "__init__.py").write_text("", encoding="utf-8")
    (instructions_dir / "__init__.py").write_text(
        "from .dynamic import DYNAMIC_IMPORTED\n", encoding="utf-8"
    )
    (instructions_dir / "dynamic.py").write_text("DYNAMIC_IMPORTED = True\n", encoding="utf-8")
    (instructions_dir / "patient.yaml").write_text(
        "namespace: demo\n"
        "group: patient\n"
        "instructions:\n"
        "  - name: DemoInstruction\n"
        "    order: 10\n"
        "    instruction: Hello\n",
        encoding="utf-8",
    )

    loaded_yaml_paths: list[str] = []

    def _fake_yaml_loader(path, *, app=None):
        loaded_yaml_paths.append(path.name)
        return []

    monkeypatch.setattr(
        "orchestrai.instructions.yaml_loader.load_yaml_instructions",
        _fake_yaml_loader,
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    for module in (
        "demo_orca_pkg",
        "demo_orca_pkg.orca",
        "demo_orca_pkg.orca.instructions",
        "demo_orca_pkg.orca.instructions.dynamic",
    ):
        monkeypatch.delitem(sys.modules, module, raising=False)

    loader = DefaultLoader()
    imported = loader.autodiscover(None, ["demo_orca_pkg.orca"])

    assert "demo_orca_pkg.orca.instructions" in imported
    assert sys.modules["demo_orca_pkg.orca.instructions"].DYNAMIC_IMPORTED is True
    assert loaded_yaml_paths == ["patient.yaml"]
