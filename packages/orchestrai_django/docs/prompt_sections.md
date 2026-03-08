# Instructions in orchestrai_django

> Prompt sections were replaced by class-based instructions in v0.5.0.

---

## Base API

```python
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca
```

`BaseInstruction` provides:

- `order` (default `50`, valid range `0-100`)
- `instruction` (static instruction text)
- `render_instruction(self)` (optional dynamic renderer, sync or async)

Use `@orca.instruction(order=...)` to register instruction classes.

---

## Example

```python
@orca.instruction(order=15)
class MedicalAccuracyInstruction(BaseInstruction):
    instruction = "Ensure medically plausible simulation behavior."
```

Dynamic example:

```python
@orca.instruction(order=0)
class PatientContextInstruction(BaseInstruction):
    def render_instruction(self) -> str:
        patient = self.context.get("patient")
        return f"Patient: {patient}" if patient else ""
```

---

## Service Composition

Instructions are mixed into services using inheritance:

```python
@orca.service
class GenerateInitialResponse(
    PatientContextInstruction,
    MedicalAccuracyInstruction,
    DjangoBaseService,
):
    pass
```

`collect_instructions()` walks this MRO, filters abstract classes, and produces deterministic order.

---

## Identity

Instruction classes resolve to the `instructions` identity domain and register in `registry.instructions`.
If derivation is ambiguous, pass explicit decorator hints (`namespace=...`, `group=...`, `name=...`).
