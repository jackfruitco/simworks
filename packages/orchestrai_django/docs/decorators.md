# Decorators

## Available Decorators

```python
from orchestrai_django.decorators import service, instruction, orca
```

- `@service` and `@orca.service` are equivalent.
- `@instruction` and `@orca.instruction` are equivalent.

## `@orca.service`

Registers a service class in the `services` domain.

Requirements:

- class must subclass `DjangoBaseService` (or compatible `BaseService` subclass)

Example:

```python
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca


@orca.service
class GenerateReply(DjangoBaseService):
    pass
```

## `@orca.instruction`

Registers an instruction class in the `instructions` domain.

Requirements:

- class must subclass `BaseInstruction`
- `order` must be an integer in `0..100`

Example:

```python
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=20)
class SafetyInstruction(BaseInstruction):
    instruction = "Do not provide real-world medical diagnosis."
```

## Namespace Export

```python
from orchestrai_django import orca

@orca.service
class MyService(...):
    ...
```

This is the recommended import style for new code.
