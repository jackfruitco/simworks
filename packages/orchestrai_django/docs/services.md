# Services

## Base Class

```python
from orchestrai_django.components.services import DjangoBaseService
```

A service:

- owns execution context (`self.context`)
- builds an agent lazily
- composes system prompts from instruction classes in its MRO
- can run immediately or through the task proxy

## Defining a Service

```python
from orchestrai.instructions import BaseInstruction
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca


@orca.instruction(order=10)
class PersonaInstruction(BaseInstruction):
    instruction = "You are a standardized patient."


@orca.service
class GenerateInitialResponse(PersonaInstruction, DjangoBaseService):
    required_context_keys = ("simulation_id",)
```

## Execution

```python
service = GenerateInitialResponse(context={"simulation_id": 42})
result = await service.arun(user_message="hello")
```

Task proxy:

```python
task_id = GenerateInitialResponse.task.using(backend="celery", queue="priority").enqueue(
    simulation_id=42,
    user_message="hello",
)
```

## Context Hooks

Useful hooks:

- `_aprepare_context(self)` for async context enrichment
- `setup(self, **ctx)` / `teardown(self, **ctx)`
- `finalize(self, result, **ctx)`

## Prompt Composition

Prompt text is derived from collected instruction classes using deterministic `(order, class_name)` sorting.
