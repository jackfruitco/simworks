# Prompt Assembly in orchestrai_django

> Services build system prompts from instruction classes resolved by `instruction_refs` or collected through MRO.

---

## Overview

`orchestrai_django` no longer uses prompt plans or a prompt engine. Prompt text is assembled from `BaseInstruction` subclasses, usually referenced by service `instruction_refs`.

At runtime:

1. `collect_instructions(type(service))` resolves `instruction_refs`; if absent, it gathers instruction classes from the service MRO.
2. Classes are ordered by `(order, class_name)` with lower `order` first.
3. Each instruction contributes text via static `instruction` or dynamic `render_instruction`.
4. The service registers each contribution as `agent.system_prompt(...)` callbacks.

---

## Defining Instructions

```python
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

@orca.instruction(order=10)
class PersonaInstruction(BaseInstruction):
    instruction = "You are a standardized patient in a training simulation."
```

Dynamic instruction:

```python
@orca.instruction(order=0)
class PatientNameInstruction(BaseInstruction):
    async def render_instruction(self) -> str:
        simulation = self.context.get("simulation")
        if simulation:
            return f"Your name is {simulation.sim_patient_full_name}."
        return "You are a standardized patient."
```

---

## Attaching Instructions to a Service

```python
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca

@orca.service
class GenerateReply(PatientNameInstruction, PersonaInstruction, DjangoBaseService):
    pass
```

This service receives both instructions automatically, in deterministic order.

Preferred modern style uses stable refs, including YAML-backed static instructions:

```python
@orca.service
class GenerateReply(DjangoBaseService):
    instruction_refs = [
        "chatlab.patient.PatientNameInstruction",
        "chatlab.patient.PatientSchemaContractInstruction",
    ]
    pass
```

Use YAML for static role, contract, behavior, and schema-note text. Use Python `render_instruction`
only for dynamic context, compact codebooks, dictionaries, or runtime data.

## Instruction Budgeting

- Keep `role`, `contract`, and `behavior` short, durable, and always included.
- Put only non-schema-enforceable constraints in `schema_notes`.
- Keep `examples` out of always-on prompts unless they protect a known regression or high-risk ambiguity.
- Keep `context` compact, preferably as JSON or tight bullets.
- Include only the needed subset of dictionaries/codebooks when possible.

---

## Runtime Introspection

```python
service = GenerateReply(context={"simulation_id": 1})
print([cls.__name__ for cls in service._instruction_classes])
```

Task serialization also renders the same instruction chain into request JSON for observability.

---

## Related Docs

- [Instructions](instructions.md)
- [Services](services.md)
- [Registries](registries.md)
- [Identity](identity.md)
