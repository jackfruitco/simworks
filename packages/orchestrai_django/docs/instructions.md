# Instructions

OrchestrAI v0.5.0 uses class-based instructions for all system prompt composition.

## Overview

- Define one instruction per class.
- Subclass `BaseInstruction`.
- Register with `@orca.instruction(order=...)`.
- Compose instructions onto services via MRO.

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
