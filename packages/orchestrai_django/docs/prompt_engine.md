# Instruction Rendering in orchestrai_django

> PromptEngine and prompt plans were removed in v0.5.0.

---

## Current Model

Instruction rendering is part of service execution:

- Instruction classes are declared with `@orca.instruction(order=...)`.
- Services compose instructions via inheritance.
- `BaseService.agent` registers one `agent.system_prompt()` callback per instruction class.
- Static and dynamic instructions are both supported.

No `PromptEngine`, `Prompt`, or `PromptSection` API exists in this version.

---

## Ordering Rules

Instruction classes are collected with `collect_instructions(...)` and ordered by:

1. `order` ascending (0 first, 100 last)
2. class name (tie-break for deterministic output)

---

## Dynamic vs Static

- Static: define class attribute `instruction = "..."`
- Dynamic: override `render_instruction(self) -> str | None` (sync or async)

Returned empty/`None` values are ignored in task prompt materialization and normalize to empty text for agent callbacks.

---

## Example

```python
from orchestrai.instructions import BaseInstruction
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca

@orca.instruction(order=0)
class ContextInstruction(BaseInstruction):
    async def render_instruction(self) -> str:
        uid = self.context.get("user_id")
        return f"Current user id: {uid}" if uid else ""

@orca.instruction(order=50)
class SafetyInstruction(BaseInstruction):
    instruction = "Never provide diagnosis outside simulation context."

@orca.service
class GenerateResponse(ContextInstruction, SafetyInstruction, DjangoBaseService):
    pass
```

---

## Migration Note

Any references to `PromptEngine`, `prompt_plan`, or `PromptSection` should be replaced with instruction classes and service MRO composition.
