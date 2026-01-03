"""Ensure legacy registry modules are no longer referenced."""

from __future__ import annotations

from pathlib import Path


FORBIDDEN_TOKENS = (
    "orchestrai.registry.singletons",
    "AppRegistry",
    "ServiceRunnerRegistry",
)


def test_no_legacy_registry_symbols_remain():
    root = Path(__file__).resolve().parents[1] / "src"
    violations: list[str] = []

    for path in root.rglob("*.py"):
        text = path.read_text()
        for token in FORBIDDEN_TOKENS:
            if token in text:
                violations.append(f"{token} found in {path.relative_to(root.parent)}")

    assert not violations, "\n".join(violations)

