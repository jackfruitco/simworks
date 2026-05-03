# orchestrai_django

`orchestrai_django` is the Django integration layer/facade for using `orchestrai` in MedSim and other Django projects.

It provides Django-native APIs so app code can integrate AI orchestration without depending on low-level `orchestrai` internals.

## What it owns

- Django-facing decorators and service wiring
- execution helpers aligned to Django runtime patterns
- settings/model/persistence integration points
- identity conventions for Django class-based registrations

## What it should not own

- framework-agnostic orchestration primitives (those belong in `orchestrai`)
- MedSim product business logic (that belongs in Django apps under `SimWorks/`)

## Relationship to `orchestrai`

- `orchestrai` defines core abstractions (providers, services, registries, lifecycle).
- `orchestrai_django` adapts those abstractions for Django projects.

When following the intended architecture, Django app code should prefer this package as its integration boundary.

## Setup overview

```bash
# standalone
pip install orchestrai-django

# within the MedSim monorepo
uv sync
```

Typical usage in a Django project:
1. configure `orchestrai`/provider settings in Django settings,
2. register instructions/services/schemas via decorators,
3. execute services through the Django helper APIs (sync or async backend),
4. persist and observe outcomes via Django hooks/signals.

## Minimal example

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

- Docs index: [`docs/index.md`](docs/index.md)
- Quick start: [`docs/quick-start.md`](docs/quick-start.md)
- Decorators: [`docs/decorators.md`](docs/decorators.md)
- Services: [`docs/services.md`](docs/services.md)
- Instructions: [`docs/instructions.md`](docs/instructions.md)
- Identity: [`docs/identity.md`](docs/identity.md)
- Registries: [`docs/registries.md`](docs/registries.md)
- Schemas: [`docs/schemas.md`](docs/schemas.md)
- Persistence: [`docs/persistence.md`](docs/persistence.md)
- Execution backends: [`docs/execution_backends.md`](docs/execution_backends.md)
- Settings: [`docs/settings.md`](docs/settings.md)
- Signals: [`docs/signals.md`](docs/signals.md)
- Prompt rendering: [`docs/prompt_engine.md`](docs/prompt_engine.md)
- MedSim platform docs: [`../../docs/index.md`](../../docs/index.md)
- Core orchestration package: [`../orchestrai/README.md`](../orchestrai/README.md)
