"""Tests for the YAML instruction loader.

Covers:
- basic loading of static and dynamic YAML instructions
- required_variables: validation success and failure
- non-required variable substitution policy (empty string fallback)
- YAMLInstructionDefinitionError for malformed definitions
- backward compatibility (files without required_variables)
- pinned class names (no identity token stripping)
- duplicate name detection
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import textwrap

import pytest

from orchestrai.components.instructions.base import BaseInstruction, MissingRequiredContextError
from orchestrai.instructions.yaml_loader import (
    YAMLInstructionDefinitionError,
    load_yaml_instructions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Write a YAML instruction file and return its path."""
    p = tmp_path / "instructions.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _run(coro):
    """Run a coroutine synchronously (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_instance(cls: type[BaseInstruction], context: dict) -> BaseInstruction:
    """Instantiate an instruction class and attach a context dict."""
    inst = cls.__new__(cls)
    inst.context = context
    return inst


# ---------------------------------------------------------------------------
# Basic loading
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_static_instruction(tmp_path: Path) -> None:
    """A static instruction sets the ``instruction`` class attribute."""
    p = _write_yaml(
        tmp_path,
        """
        namespace: demo
        group: test

        instructions:
          - name: HelloInstruction
            order: 10
            instruction: "Say hello."
        """,
    )
    classes = load_yaml_instructions(p)
    assert len(classes) == 1
    cls = classes[0]
    assert cls.__name__ == "HelloInstruction"
    assert cls.instruction == "Say hello."
    assert cls.order == 10
    assert cls.abstract is False


@pytest.mark.unit
def test_load_dynamic_instruction_detects_template_vars(tmp_path: Path) -> None:
    """Instructions with ``${variable}`` placeholders are classified as dynamic."""
    p = _write_yaml(
        tmp_path,
        """
        namespace: demo
        group: test

        instructions:
          - name: GreetInstruction
            order: 5
            instruction: "Hello, ${patient_name}."
        """,
    )
    classes = load_yaml_instructions(p)
    assert len(classes) == 1
    cls = classes[0]
    assert cls.__name__ == "GreetInstruction"
    # Dynamic instructions override render_instruction, not instruction attr.
    assert cls.instruction is None
    assert hasattr(cls, "_yaml_template")


@pytest.mark.unit
def test_load_multiple_instructions(tmp_path: Path) -> None:
    """Multiple instructions are returned in file order."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: FirstInstruction
            order: 10
            instruction: "First."
          - name: SecondInstruction
            order: 20
            instruction: "Second."
        """,
    )
    classes = load_yaml_instructions(p)
    assert [c.__name__ for c in classes] == ["FirstInstruction", "SecondInstruction"]


@pytest.mark.unit
def test_load_empty_file_returns_empty_list(tmp_path: Path) -> None:
    """Files with no instructions key return an empty list."""
    p = tmp_path / "empty.yaml"
    p.write_text("{}", encoding="utf-8")
    assert load_yaml_instructions(p) == []


@pytest.mark.unit
def test_load_default_order(tmp_path: Path) -> None:
    """Order defaults to 50 when omitted."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: DefaultOrderInstruction
            instruction: "Some text."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    assert cls.order == 50


# ---------------------------------------------------------------------------
# Identity: name is pinned, no token stripping
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_class_name_not_stripped(tmp_path: Path) -> None:
    """Class name must match the YAML name exactly (no token stripping)."""
    p = _write_yaml(
        tmp_path,
        """
        namespace: chatlab
        group: patient

        instructions:
          - name: PatientNameInstruction
            order: 0
            instruction: "Static text."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    # __name__ must be exactly "PatientNameInstruction", not "PatientName"
    assert cls.__name__ == "PatientNameInstruction"
    # The identity name should also be pinned
    assert cls.name == "PatientNameInstruction"


@pytest.mark.unit
def test_namespace_and_group_stored(tmp_path: Path) -> None:
    """namespace and group from the file header are stored on each class."""
    p = _write_yaml(
        tmp_path,
        """
        namespace: myapp
        group: mygroup

        instructions:
          - name: SomeInstruction
            instruction: "Text."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    assert cls.namespace == "myapp"
    assert cls.group == "mygroup"


# ---------------------------------------------------------------------------
# Rendering: static instructions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_static_instruction(tmp_path: Path) -> None:
    """Static instructions return their text from render_instruction()."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: StaticInstruction
            instruction: "Do the thing."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {})
    result = _run(inst.render_instruction())
    assert result == "Do the thing."


# ---------------------------------------------------------------------------
# Rendering: dynamic instructions with variable substitution
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_dynamic_substitution(tmp_path: Path) -> None:
    """${variable} placeholders are replaced from context."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: GreetInstruction
            instruction: "Hello, ${patient_name}. You have ${complaint}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {"patient_name": "Alice", "complaint": "a headache"})
    result = _run(inst.render_instruction())
    assert result == "Hello, Alice. You have a headache."


@pytest.mark.unit
def test_render_non_required_variable_falls_back_to_empty_string(tmp_path: Path) -> None:
    """Non-required variables absent from context render as empty string.

    This is the documented policy for optional placeholders: render empty,
    not raise.  Use ``required_variables`` to declare variables that must
    be present.
    """
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: OptionalVarInstruction
            instruction: "Hello, ${name}. Note: ${optional_note}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {"name": "Bob"})
    result = _run(inst.render_instruction())
    # ${optional_note} is absent → rendered as empty string
    assert result == "Hello, Bob. Note: ."


# ---------------------------------------------------------------------------
# required_variables: success path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_required_variables_stored_on_class(tmp_path: Path) -> None:
    """required_variables are stored as a tuple on the generated class."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: ContextInstruction
            required_variables:
              - patient_name
              - chief_complaint
            instruction: "${patient_name} has ${chief_complaint}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    assert cls.required_variables == ("patient_name", "chief_complaint")


@pytest.mark.unit
def test_required_variables_render_success(tmp_path: Path) -> None:
    """Rendering succeeds when all required variables are present."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: ContextInstruction
            required_variables:
              - patient_name
              - chief_complaint
            instruction: "Patient ${patient_name}: ${chief_complaint}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {"patient_name": "Alice", "chief_complaint": "chest pain"})
    result = _run(inst.render_instruction())
    assert result == "Patient Alice: chest pain."


@pytest.mark.unit
def test_required_variables_on_static_instruction(tmp_path: Path) -> None:
    """Static instructions (no placeholders) with required_variables also validate."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: StaticWithReqs
            required_variables:
              - simulation_id
            instruction: "A static instruction that still needs context validation."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {"simulation_id": 42})
    result = _run(inst.render_instruction())
    assert "static instruction" in result


# ---------------------------------------------------------------------------
# required_variables: failure path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_required_variable_raises(tmp_path: Path) -> None:
    """Rendering with a missing required variable raises MissingRequiredContextError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: PatientContextInstruction
            required_variables:
              - patient_name
              - chief_complaint
            instruction: "Patient: ${patient_name}. Complaint: ${chief_complaint}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    # Only patient_name present; chief_complaint missing
    inst = _make_instance(cls, {"patient_name": "Alice"})
    with pytest.raises(MissingRequiredContextError) as exc_info:
        _run(inst.render_instruction())

    err = exc_info.value
    assert err.instruction_name == "PatientContextInstruction"
    assert "chief_complaint" in err.missing_keys
    assert "patient_name" in err.available_keys


@pytest.mark.unit
def test_missing_required_variable_error_message_is_informative(tmp_path: Path) -> None:
    """Error message includes instruction name, missing key, and available keys."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: NeedsSimId
            required_variables:
              - simulation_id
            instruction: "Sim ${simulation_id}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {"user_id": 7})
    with pytest.raises(MissingRequiredContextError) as exc_info:
        _run(inst.render_instruction())
    msg = str(exc_info.value)
    assert "NeedsSimId" in msg
    assert "simulation_id" in msg
    assert "user_id" in msg  # available key shown for diagnosis


@pytest.mark.unit
def test_missing_required_variable_all_absent(tmp_path: Path) -> None:
    """When all required variables are absent the error lists all of them."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: MultiReqInstruction
            required_variables:
              - alpha
              - beta
              - gamma
            instruction: "${alpha} ${beta} ${gamma}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {})
    with pytest.raises(MissingRequiredContextError) as exc_info:
        _run(inst.render_instruction())
    err = exc_info.value
    assert set(err.missing_keys) == {"alpha", "beta", "gamma"}


@pytest.mark.unit
def test_missing_required_variable_on_static_instruction(tmp_path: Path) -> None:
    """Static instructions with required_variables also raise on missing context."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: StaticWithReq
            required_variables:
              - simulation_id
            instruction: "Static text that still requires simulation_id."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {})
    with pytest.raises(MissingRequiredContextError) as exc_info:
        _run(inst.render_instruction())
    assert "simulation_id" in exc_info.value.missing_keys


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_legacy_yaml_without_required_variables(tmp_path: Path) -> None:
    """YAML files that do not define required_variables continue to work."""
    p = _write_yaml(
        tmp_path,
        """
        namespace: chatlab
        group: patient

        instructions:
          - name: LegacyInstruction
            order: 30
            instruction: |
              Do the legacy thing.
        """,
    )
    classes = load_yaml_instructions(p)
    assert len(classes) == 1
    cls = classes[0]
    assert cls.required_variables == ()
    inst = _make_instance(cls, {})
    result = _run(inst.render_instruction())
    assert "legacy thing" in result


@pytest.mark.unit
def test_legacy_dynamic_yaml_without_required_variables(tmp_path: Path) -> None:
    """Dynamic YAML without required_variables: missing vars render as empty string."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: LegacyDynamic
            instruction: "Hello, ${name}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {})
    result = _run(inst.render_instruction())
    assert result == "Hello, ."  # empty string for missing ${name}


# ---------------------------------------------------------------------------
# YAMLInstructionDefinitionError: validation errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_missing_name(tmp_path: Path) -> None:
    """Instructions without a name key raise YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - order: 10
            instruction: "Some text."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="missing required key 'name'"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_empty_name(tmp_path: Path) -> None:
    """An empty name string raises YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: ""
            instruction: "Some text."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="'name' must be a non-empty string"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_missing_instruction_text(tmp_path: Path) -> None:
    """Instructions without an instruction key raise YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: NoTextInstruction
            order: 5
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="missing required key 'instruction'"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_order_not_integer(tmp_path: Path) -> None:
    """A non-integer order raises YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: BadOrderInstruction
            order: "high"
            instruction: "Text."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="'order' must be an integer"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_order_out_of_range(tmp_path: Path) -> None:
    """An order outside [0, 100] raises YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: BigOrderInstruction
            order: 999
            instruction: "Text."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="'order' must be between"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_required_variables_not_list(tmp_path: Path) -> None:
    """required_variables that is not a list raises YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: BadReqVars
            required_variables: patient_name
            instruction: "${patient_name}."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="'required_variables' must be a list"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_required_variables_contains_non_string(tmp_path: Path) -> None:
    """required_variables entries that are not strings raise YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: BadReqVarEntry
            required_variables:
              - 42
            instruction: "Text."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="must be a non-empty string"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_duplicate_name(tmp_path: Path) -> None:
    """Two instructions sharing the same name raise YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: DupeName
            instruction: "First."
          - name: DupeName
            instruction: "Second."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="duplicate instruction name"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_instructions_not_a_list(tmp_path: Path) -> None:
    """instructions key that is not a list raises YAMLInstructionDefinitionError."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          name: SomeName
          instruction: "Flat dict, not a list."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError, match="'instructions' must be a list"):
        load_yaml_instructions(p)


@pytest.mark.unit
def test_error_message_includes_file_path(tmp_path: Path) -> None:
    """Error messages include the file path for easy diagnosis."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: ""
            instruction: "Text."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError) as exc_info:
        load_yaml_instructions(p)
    assert str(p) in str(exc_info.value)


@pytest.mark.unit
def test_error_validates_all_items_before_registering(tmp_path: Path) -> None:
    """Validation runs on all items before any class is created.

    This ensures a file with one bad item does not partially register its
    preceding valid items.
    """
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: GoodInstruction
            instruction: "Good."
          - name: BadInstruction
            order: "not-an-int"
            instruction: "Bad."
        """,
    )
    with pytest.raises(YAMLInstructionDefinitionError):
        load_yaml_instructions(p)


# ---------------------------------------------------------------------------
# BaseInstruction._validate_context directly
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_context_passes_when_all_present(tmp_path: Path) -> None:
    """_validate_context does not raise when all required vars are present."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: ReqInstruction
            required_variables:
              - x
              - y
            instruction: "${x} + ${y}."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {"x": "1", "y": "2"})
    inst._validate_context(inst.context)  # must not raise


@pytest.mark.unit
def test_validate_context_noop_when_no_required_variables(tmp_path: Path) -> None:
    """_validate_context is a no-op when required_variables is empty."""
    p = _write_yaml(
        tmp_path,
        """
        instructions:
          - name: NoReqInstruction
            instruction: "No requirements."
        """,
    )
    (cls,) = load_yaml_instructions(p)
    inst = _make_instance(cls, {})
    inst._validate_context({})  # must not raise


# ---------------------------------------------------------------------------
# BaseInstruction: MissingRequiredContextError attributes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_required_context_error_attributes() -> None:
    """MissingRequiredContextError exposes structured attributes."""
    err = MissingRequiredContextError(
        instruction_name="MyInstruction",
        missing_keys=["foo", "bar"],
        available_keys=["baz"],
    )
    assert err.instruction_name == "MyInstruction"
    assert err.missing_keys == ["foo", "bar"]
    assert err.available_keys == ["baz"]
    assert isinstance(err, ValueError)
