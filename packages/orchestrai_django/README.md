# orchestrai_django

Django integration for OrchestrAI with class-based services and instruction composition.

## Highlights

- `@orca.service` for registering service classes.
- `@orca.instruction(order=...)` for deterministic system prompt composition.
- Django-aware identity derivation and registry checks.
- Task dispatch helpers via `Service.task` for immediate/async backends.
- Django schema and codec compatibility components.

## Core Imports

```python
from orchestrai_django.decorators import orca, service, instruction
from orchestrai_django.components.services import DjangoBaseService
from orchestrai.instructions import BaseInstruction
```

## Minimal Example

```python
from orchestrai.instructions import BaseInstruction
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca


@orca.instruction(order=10)
class PersonaInstruction(BaseInstruction):
    instruction = "You are a standardized patient."


@orca.service
class GenerateInitialResponse(PersonaInstruction, DjangoBaseService):
    pass
```

## Documentation

See `packages/orchestrai_django/docs/` for full guides.
