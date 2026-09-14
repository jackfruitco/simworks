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

Use `@orca.instruction(order=...)` to register Python instruction classes. Static app-local
instructions may also be generated from YAML and referenced by identity.

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

New services should prefer `instruction_refs`:

```python
@orca.service
class GenerateInitialResponse(DjangoBaseService):
    instruction_refs = [
        "chatlab.patient.PatientNameInstruction",
        "chatlab.patient.PatientSchemaContractInstruction",
    ]
    pass
```

## Budgeting Convention

Use YAML for short, durable `role`, `contract`, `behavior`, and `schema_notes` instructions.
Use Python for dynamic `context`, compact dictionaries, and codebooks. Keep examples optional and
out of always-on prompts unless they address a known regression, eval/debug need, or high-risk
ambiguity.

---

## Identity

Instruction classes resolve to the `instructions` identity domain and register in `registry.instructions`.
If derivation is ambiguous, pass explicit decorator hints (`namespace=...`, `group=...`, `name=...`).
