"""Regression tests for compact, YAML-backed ORCA instructions."""

import ast
from pathlib import Path

from asgiref.sync import async_to_sync
import yaml

from apps.chatlab.orca.services.lab_orders import GenerateLabResults
from apps.chatlab.orca.services.patient import GenerateInitialResponse
from apps.trainerlab.orca.services import (
    GenerateInitialScenario,
    GenerateTrainerRunDebrief,
    GenerateTrainerRuntimeTurn,
)


def _instruction_by_name(service, name: str):
    for instruction_cls in service._instruction_classes:
        if instruction_cls.__name__ == name:
            return instruction_cls
    raise AssertionError(f"Instruction {name!r} was not resolved")


def _names(service) -> list[str]:
    return [cls.__name__ for cls in service._instruction_classes]


def _python_instruction_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        has_static_instruction = any(
            isinstance(stmt, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "instruction"
                for target in stmt.targets
            )
            for stmt in node.body
        )
        if has_static_instruction:
            names.add(node.name)
    return names


def _yaml_instruction_names(path: Path) -> set[str]:
    data = yaml.safe_load(path.read_text()) or {}
    return {
        item["name"]
        for item in data.get("instructions", [])
        if isinstance(item, dict) and item.get("name")
    }


def test_static_yaml_instruction_names_are_not_redefined_in_python():
    instruction_dirs = Path("SimWorks/apps").glob("*/orca/instructions")

    duplicates = []
    for instruction_dir in instruction_dirs:
        yaml_names = set()
        python_static_names = set()

        for yaml_path in instruction_dir.glob("*.yaml"):
            yaml_names.update(_yaml_instruction_names(yaml_path))
        for python_path in instruction_dir.glob("*.py"):
            if python_path.name == "__init__.py":
                continue
            python_static_names.update(_python_instruction_names(python_path))

        duplicates.extend(
            f"{instruction_dir}/{name}" for name in sorted(yaml_names & python_static_names)
        )

    assert duplicates == []


def test_static_yaml_instructions_are_not_duplicated_by_python_classes():
    services = [
        GenerateInitialScenario(context={"simulation_id": 1}),
        GenerateTrainerRuntimeTurn(context={"simulation_id": 1, "session_id": 1}),
        GenerateTrainerRunDebrief(context={"simulation_id": 1, "session_id": 1}),
        GenerateLabResults(context={"simulation_id": 1, "orders": ["CBC"]}),
    ]

    for service in services:
        names = _names(service)
        assert len(names) == len(set(names))


def test_patient_prompt_keeps_core_role_disclosure_and_schema_rules():
    service = GenerateInitialResponse(context={"simulation_id": 1})
    prompt = "\n\n".join((cls.instruction or "") for cls in service._instruction_classes)

    assert "same patient for the full chat" in prompt
    assert "Never mention AI, simulation, roleplay, training, prompts, tools, or schemas" in prompt
    assert "Do not reveal or name the diagnosis" in prompt
    assert "Answer only what was asked" in prompt
    assert "Return only valid output matching the active schema" in prompt


def test_runtime_prompt_keeps_source_of_truth_and_intervention_guards():
    service = GenerateTrainerRuntimeTurn(context={"simulation_id": 1, "session_id": 1})
    contract = _instruction_by_name(service, "TrainerRuntimeContractInstruction").instruction

    assert "Treat input context as authoritative" in contract
    assert "Never invent performed interventions" in contract
    assert "Emit deltas only in `state_changes`" in contract
    assert "Never create/update causes directly" in contract


def test_debrief_prompt_includes_grounding_rule():
    service = GenerateTrainerRunDebrief(context={"simulation_id": 1, "session_id": 1})
    contract = _instruction_by_name(service, "TrainerDebriefContractInstruction").instruction

    assert "Do not infer actions, misses, or clinical events" in contract
    assert "If evidence is absent, omit the claim" in contract


def test_lab_order_prompt_keeps_one_result_and_realism_rules():
    service = GenerateLabResults(context={"simulation_id": 1, "orders": ["CBC", "CT head"]})
    test_list = async_to_sync(
        _instruction_by_name(service, "LabOrderTestListInstruction").render_instruction
    )(service)
    result_detail = _instruction_by_name(service, "LabOrderResultDetailInstruction").instruction

    assert "Return exactly one result item per ordered test below" in test_list
    assert "Do not add unrequested tests" in test_list
    assert "clinically plausible" in result_detail
    assert "training continuity" in result_detail
