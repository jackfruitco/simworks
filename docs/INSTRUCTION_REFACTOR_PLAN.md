# Instruction Refactor v0.5.0 (Hard Cutover)

## Summary
- Merge `docs/INSTRUCTION_REFACTOR_PLAN.md` from `origin/claude/review-instruction-plan-K1Wwx` into `orchestrai/refactor-instructions`, then implement a hard migration from `@system_prompt` + PromptKit/PromptSection to class-based instruction MRO.
- Preserve decorator ergonomics by keeping existing `service` imports while adding `orca.service` and `orca.instruction`.
- Ship as breaking release `0.5.0` for `orchestrai` and `orchestrai-django`, with full docs rewrite in the same PR.

## Public API and Contract Changes
- Add new instruction API: `orchestrai.instructions.BaseInstruction`, `orchestrai.instructions.collect_instructions`, and `@orca.instruction(order=...)` in both core and Django decorator surfaces.
- Add `orca` namespace exports from `orchestrai.decorators`, `orchestrai_django.decorators`, `orchestrai`, and `orchestrai_django`; keep `service` alias exports unchanged.
- Introduce `INSTRUCTIONS_DOMAIN="instructions"` and `registry.instructions`; update domain inference to detect instruction classes.
- Remove legacy APIs completely: `orchestrai.prompts`, `@system_prompt`, `collect_prompts`, `render_prompt_methods`, PromptKit (`orchestrai.components.promptkit`), PromptSection decorator/registry surface, and Django promptkit/prompt tag modules.
- Remove prompt-section identity domain support from resolver-facing constants and registry exports (no compatibility shims).

## Implementation Changes
- Core framework foundation: add instruction base/collector package, instruction decorator component, decorator lazy exports, and domain/registry wiring; update `BaseService` to cache `_instruction_classes` and register `agent.system_prompt()` callbacks from instruction classes with deterministic `(order, class_name)` ordering and sync/async render support.
- Django runtime integration: add Django instruction decorator, include `instructions` in component discovery, update task request serialization to build system prompt text from instruction classes, and replace prompt-section checks with instruction-presence checks in service pairing/registry checks.
- SimWorks migration: create `orca/instructions/` modules for common/chatlab/simcore prompt content, move each existing prompt method to instruction classes (static `instruction` or dynamic `render_instruction`), and rewrite service inheritance to compose instructions via MRO while preserving existing non-prompt mixins (`PreviousResponseMixin`, `FeedbackMixin`) and response schema behavior.
- Hard legacy removal sweep: delete prompt modules/directories and prompt-section/promptkit integration code paths; update loader/discovery suffixes and any remaining type hints/imports that reference Prompt/PromptSection/PromptPlan.
- Documentation rewrite: update all prompt-section/prompt-engine/system-prompt docs to instruction architecture, including `packages/orchestrai/docs/*`, `packages/orchestrai_django/docs/*`, `packages/orchestrai_django/README.md`, and repo docs that describe registries/lifecycle behavior.

## Test Plan
- Core unit tests: replace prompt decorator tests with instruction decorator/collector tests, add order validation (`0-100`), subclass enforcement, abstract-class skipping, and `orca` namespace import coverage.
- Core registry/identity tests: replace PromptSection routing/domain tests with instruction routing/domain tests and update supported-domain assertions.
- Django tests: update integration tests to assert `_instruction_classes` collection and instruction rendering, and update checks tests to validate instruction registry and instruction-presence warnings/errors.
- SimWorks tests: update chatlab/simworks service tests to assert expected instruction classes on services and validate dynamic instruction rendering behavior for patient/stitch/feedback contexts.
- Validation commands: run targeted suites first (`packages/orchestrai/tests`, `packages/orchestrai_django/tests`, `tests/chatlab`, `tests/simworks`), then full `uv run pytest`, plus `uv run python SimWorks/manage.py check` and migration/check commands already used in this repo.

## Assumptions and Defaults
- Hard removal is intentional: legacy prompt/prompt-section imports are not preserved or warned; they should fail fast.
- Alias policy is intentional: `service` remains supported while `orca.service` and `orca.instruction` become the documented primary API.
- Instruction ordering semantics are fixed to lower `order` first, with class-name tiebreak for determinism.
- Dynamic instruction methods may be sync or async; runtime must normalize both consistently in service execution and task serialization.
