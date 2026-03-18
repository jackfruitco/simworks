"""Tests for instruction_refs resolution and collect_instructions().

Covers:
- 3-part identity ref resolution (namespace.group.ClassName)
- 4-part identity ref resolution (domain.namespace.group.ClassName)
- invalid ref format raises ValueError (bare names not supported)
- missing ref raises ValueError with diagnostic labels
- ordering is driven by instruction metadata (order), not list position
- deduplication of duplicate refs in a single list
- MRO fallback (instruction_refs absent → MRO walk)
- mixed identity + MRO fallback correctness
"""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
from typing import ClassVar

import pytest

from orchestrai._state import push_current_app
from orchestrai.components.instructions.base import BaseInstruction
from orchestrai.components.instructions.collector import collect_instructions
from orchestrai.identity.domains import INSTRUCTIONS_DOMAIN
from orchestrai.registry import ComponentStore

# ---------------------------------------------------------------------------
# Test instruction stubs
# ---------------------------------------------------------------------------


class _InstrA(BaseInstruction):
    abstract = False
    namespace = "testns"
    group = "grp"
    name = "InstrA"
    order = 30
    instruction = "Instruction A."


class _InstrB(BaseInstruction):
    abstract = False
    namespace = "testns"
    group = "grp"
    name = "InstrB"
    order = 10
    instruction = "Instruction B."


class _InstrC(BaseInstruction):
    abstract = False
    namespace = "other"
    group = "section"
    name = "InstrC"
    order = 20
    instruction = "Instruction C."


# A second instruction that has the same __name__ as _InstrA but lives in a
# different namespace/group — used to verify name-collision safety.
class _InstrAClone(BaseInstruction):
    abstract = False
    namespace = "colliding"
    group = "grp"
    name = "InstrA"  # same name, different identity
    order = 5
    instruction = "Clone of A."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(*instruction_classes: type[BaseInstruction]) -> SimpleNamespace:
    """Create a minimal mock app with a ComponentStore pre-loaded with instructions."""
    store = ComponentStore()
    registry = store.registry(INSTRUCTIONS_DOMAIN)
    for cls in instruction_classes:
        registry.register(cls)
    return SimpleNamespace(components=store, component_store=store)


def _write_package_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _clear_demo_modules(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# 3-part identity ref resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_three_part_ref_resolves_correct_class() -> None:
    """3-part 'namespace.group.ClassName' resolves to the registered class."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = ["testns.grp.InstrA"]

    app = _make_app(_InstrA, _InstrB, _InstrC)
    with push_current_app(app):
        result = collect_instructions(_Service)

    assert result == [_InstrA]


@pytest.mark.unit
def test_three_part_ref_multiple_instructions() -> None:
    """Multiple 3-part refs each resolve to the right class."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = [
            "testns.grp.InstrA",
            "other.section.InstrC",
        ]

    app = _make_app(_InstrA, _InstrB, _InstrC)
    with push_current_app(app):
        result = collect_instructions(_Service)

    # Ordered by (order, __name__): C=20 < A=30
    assert result == [_InstrC, _InstrA]


@pytest.mark.unit
def test_three_part_ref_distinguishes_namespaces() -> None:
    """3-part refs are namespace-aware; same class name in different ns resolves correctly."""

    class _ServiceA:
        instruction_refs: ClassVar[list[str]] = ["testns.grp.InstrA"]

    class _ServiceClone:
        instruction_refs: ClassVar[list[str]] = ["colliding.grp.InstrA"]

    app = _make_app(_InstrA, _InstrAClone)
    with push_current_app(app):
        result_a = collect_instructions(_ServiceA)
        result_clone = collect_instructions(_ServiceClone)

    assert result_a == [_InstrA]
    assert result_clone == [_InstrAClone]
    # These are genuinely different classes — proves no namespace collision
    assert result_a[0] is not result_clone[0]


@pytest.mark.unit
def test_three_part_ref_lazy_imports_python_instruction_package(monkeypatch, tmp_path) -> None:
    """Unresolved 3-part refs lazily import the namespace instruction package."""

    package_root = tmp_path / "apps" / "demo"
    instructions_dir = package_root / "orca" / "instructions"
    _write_package_file(tmp_path / "apps" / "__init__.py", "")
    _write_package_file(package_root / "__init__.py", "")
    _write_package_file(package_root / "orca" / "__init__.py", "")
    _write_package_file(
        instructions_dir / "__init__.py",
        """
        from .runtime import DynamicInstruction
        """,
    )
    _write_package_file(
        instructions_dir / "runtime.py",
        """
        from orchestrai.components.instructions.base import BaseInstruction
        from orchestrai.decorators.components.instruction_decorator import InstructionDecorator

        instruction = InstructionDecorator()

        @instruction(namespace="demo", group="runtime", order=40)
        class DynamicInstruction(BaseInstruction):
            instruction = "Dynamic instruction."
        """,
    )

    _clear_demo_modules("apps")
    monkeypatch.syspath_prepend(str(tmp_path))

    try:

        class _Service:
            instruction_refs: ClassVar[list[str]] = ["demo.runtime.DynamicInstruction"]

        app = _make_app()
        with push_current_app(app):
            result = collect_instructions(_Service)
    finally:
        _clear_demo_modules("apps")

    assert [cls.name for cls in result] == ["DynamicInstruction"]


@pytest.mark.unit
def test_three_part_ref_supports_mixed_lazy_python_and_yaml_resolution(
    monkeypatch, tmp_path
) -> None:
    """Python-import fallback and YAML lazy-load can satisfy refs in the same namespace/group."""

    package_root = tmp_path / "apps" / "demo"
    instructions_dir = package_root / "orca" / "instructions"
    _write_package_file(tmp_path / "apps" / "__init__.py", "")
    _write_package_file(package_root / "__init__.py", "")
    _write_package_file(package_root / "orca" / "__init__.py", "")
    _write_package_file(
        instructions_dir / "__init__.py",
        """
        from .runtime import DynamicInstruction
        """,
    )
    _write_package_file(
        instructions_dir / "runtime.py",
        """
        from orchestrai.components.instructions.base import BaseInstruction
        from orchestrai.decorators.components.instruction_decorator import InstructionDecorator

        instruction = InstructionDecorator()

        @instruction(namespace="demo", group="runtime", order=40)
        class DynamicInstruction(BaseInstruction):
            instruction = "Dynamic instruction."
        """,
    )
    _write_package_file(
        instructions_dir / "runtime.yaml",
        """
        namespace: demo
        group: runtime

        instructions:
          - name: StaticInstruction
            order: 10
            instruction: Static instruction.
        """,
    )

    _clear_demo_modules("apps")
    monkeypatch.syspath_prepend(str(tmp_path))

    try:

        class _Service:
            instruction_refs: ClassVar[list[str]] = [
                "demo.runtime.DynamicInstruction",
                "demo.runtime.StaticInstruction",
            ]

        app = _make_app()
        with push_current_app(app):
            result = collect_instructions(_Service)
    finally:
        _clear_demo_modules("apps")

    assert [cls.name for cls in result] == ["StaticInstruction", "DynamicInstruction"]


# ---------------------------------------------------------------------------
# 4-part identity ref resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_four_part_ref_resolves_correct_class() -> None:
    """4-part 'domain.namespace.group.ClassName' also resolves correctly."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = ["instructions.testns.grp.InstrA"]

    app = _make_app(_InstrA)
    with push_current_app(app):
        result = collect_instructions(_Service)

    assert result == [_InstrA]


# ---------------------------------------------------------------------------
# Invalid ref format → clear error
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bare_name_raises_value_error() -> None:
    """A bare name (no dots) raises ValueError immediately — no deprecation path."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = ["InstrB"]

    app = _make_app(_InstrB)
    with push_current_app(app), pytest.raises(ValueError, match="invalid ref format"):
        collect_instructions(_Service)


@pytest.mark.unit
def test_one_dot_ref_raises_value_error() -> None:
    """A 2-part ref (one dot) raises ValueError with a format hint."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = ["testns.InstrA"]

    app = _make_app(_InstrA)
    with push_current_app(app), pytest.raises(ValueError, match="invalid ref format"):
        collect_instructions(_Service)


@pytest.mark.unit
def test_invalid_ref_error_suggests_three_part_format() -> None:
    """The error message for an invalid format mentions the expected 3-part format."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = ["InstrA"]

    app = _make_app(_InstrA)
    with push_current_app(app), pytest.raises(ValueError) as exc_info:
        collect_instructions(_Service)

    assert "namespace.group.ClassName" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Missing ref → clear error
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_three_part_ref_raises_value_error() -> None:
    """A 3-part ref that resolves to nothing raises ValueError."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = ["testns.grp.NoSuchInstruction"]

    app = _make_app(_InstrA)
    with push_current_app(app), pytest.raises(ValueError, match=r"testns\.grp\.NoSuchInstruction"):
        collect_instructions(_Service)


@pytest.mark.unit
def test_missing_ref_error_includes_available_labels() -> None:
    """The error message includes available registry labels for diagnosis."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = ["testns.grp.Ghost"]

    app = _make_app(_InstrA, _InstrB)
    with push_current_app(app), pytest.raises(ValueError) as exc_info:
        collect_instructions(_Service)

    msg = str(exc_info.value)
    # Should mention at least one available identity label
    assert "InstrA" in msg or "Available" in msg


@pytest.mark.unit
def test_missing_bare_name_raises_value_error() -> None:
    """A bare name raises ValueError with the ref text in the message."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = ["GhostInstruction"]

    app = _make_app(_InstrA)
    with push_current_app(app), pytest.raises(ValueError, match="GhostInstruction"):
        collect_instructions(_Service)


# ---------------------------------------------------------------------------
# Ordering: driven by metadata, not list position
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ordering_is_driven_by_instruction_order_not_list_position() -> None:
    """collect_instructions sorts by (order, __name__), not by list position.

    _InstrA has order=30, _InstrB has order=10, _InstrC has order=20.
    Even if listed as [A, C, B], result must be [B(10), C(20), A(30)].
    """

    class _Service:
        instruction_refs: ClassVar[list[str]] = [
            "testns.grp.InstrA",  # order 30 — listed first
            "other.section.InstrC",  # order 20 — listed second
            "testns.grp.InstrB",  # order 10 — listed last
        ]

    app = _make_app(_InstrA, _InstrB, _InstrC)
    with push_current_app(app):
        result = collect_instructions(_Service)

    assert result == [_InstrB, _InstrC, _InstrA]
    assert [c.order for c in result] == [10, 20, 30]


@pytest.mark.unit
def test_same_order_is_broken_by_class_name() -> None:
    """When two instructions share the same order, __name__ breaks the tie."""

    class _Alpha(BaseInstruction):
        abstract = False
        namespace = "ns"
        group = "g"
        name = "Alpha"
        order = 50
        instruction = "Alpha."

    class _Zeta(BaseInstruction):
        abstract = False
        namespace = "ns"
        group = "g"
        name = "Zeta"
        order = 50
        instruction = "Zeta."

    class _Service:
        instruction_refs: ClassVar[list[str]] = [
            "ns.g.Zeta",  # listed first
            "ns.g.Alpha",  # listed second
        ]

    app = _make_app(_Alpha, _Zeta)
    with push_current_app(app):
        result = collect_instructions(_Service)

    # Alpha < Zeta alphabetically by identity name → Alpha first despite being listed second
    assert [getattr(c, "name", c.__name__) for c in result] == ["Alpha", "Zeta"]


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_duplicate_refs_are_deduplicated() -> None:
    """The same ref appearing twice in instruction_refs is included only once."""

    class _Service:
        instruction_refs: ClassVar[list[str]] = [
            "testns.grp.InstrA",
            "testns.grp.InstrA",  # duplicate
        ]

    app = _make_app(_InstrA)
    with push_current_app(app):
        result = collect_instructions(_Service)

    assert len(result) == 1
    assert result[0] is _InstrA


# ---------------------------------------------------------------------------
# MRO fallback (instruction_refs absent)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mro_fallback_collects_base_instructions() -> None:
    """When instruction_refs is absent, MRO is walked for BaseInstruction subclasses."""

    class _InstrMRO(BaseInstruction):
        abstract = False
        namespace = "mro"
        group = "grp"
        name = "InstrMRO"
        order = 5
        instruction = "MRO instruction."

    class _ServiceMRO(_InstrMRO):
        # No instruction_refs; MRO walk should find _InstrMRO
        pass

    result = collect_instructions(_ServiceMRO)
    assert _InstrMRO in result


@pytest.mark.unit
def test_mro_fallback_skips_abstract_instructions() -> None:
    """MRO walk skips instructions with abstract=True (base classes)."""

    class _AbstractInstr(BaseInstruction):
        abstract = True  # base / abstract
        namespace = "mro"
        group = "grp"
        name = "AbstractInstr"
        order = 5
        instruction = "Abstract — should not appear."

    class _ConcreteInstr(BaseInstruction):
        abstract = False
        namespace = "mro"
        group = "grp"
        name = "ConcreteInstr"
        order = 10
        instruction = "Concrete — should appear."

    class _ServiceMRO(_AbstractInstr, _ConcreteInstr):
        pass

    result = collect_instructions(_ServiceMRO)
    assert _AbstractInstr not in result
    assert _ConcreteInstr in result


@pytest.mark.unit
def test_instruction_refs_none_falls_back_to_mro() -> None:
    """instruction_refs = None falls back to MRO (same as absent)."""

    class _InstrMRO2(BaseInstruction):
        abstract = False
        namespace = "mro"
        group = "grp"
        name = "InstrMRO2"
        order = 5
        instruction = "MRO2."

    class _ServiceNoneRefs(_InstrMRO2):
        instruction_refs = None  # explicit None → MRO

    result = collect_instructions(_ServiceNoneRefs)
    assert _InstrMRO2 in result
