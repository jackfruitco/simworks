# Instructions

OrchestrAI v0.5.0 uses instruction classes for all system prompt composition.

## Overview

- Define one instruction per class.
- Subclass `BaseInstruction`.
- Register Python instructions with `@orca.instruction(order=...)`.
- Prefer `instruction_refs` on services; MRO composition remains supported for legacy code.
- App-local YAML files are the preferred source of truth for static role/contract/behavior text.
- Python instruction classes should assemble dynamic context, codebooks, dictionaries, and compact runtime data.

## Example

```python
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=10)
class PersonaInstruction(BaseInstruction):
    instruction = "You are a standardized patient."
```

Then include the instruction class in your service inheritance:

```python
@orca.service
class GenerateInitialResponse(PersonaInstruction, DjangoBaseService):
    ...
```

Dynamic content can be implemented with `async def render_instruction(self) -> str | None`.

## Instruction Budgeting

Keep durable prompt text short and non-duplicated:

- `role`: durable identity and authority boundary.
- `contract`: concise task/output contract.
- `behavior`: durable behavior that the schema cannot enforce.
- `schema_notes`: only natural-language constraints not already enforced by a strict schema.
- `examples`: optional; include only for known regressions, eval/debug mode, or high-risk ambiguity.
- `context`: dynamic and compact; prefer JSON or compact bullets.
- `dictionaries/codebooks`: include only the subset required for the current task when possible.

Do not duplicate static YAML instructions in Python classes. If a service needs both static text and
dynamic context, reference the YAML instruction and add a separate Python dynamic instruction.
