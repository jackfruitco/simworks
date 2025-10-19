# Prompts and Prompt Plans in simcore_ai_django

> Prompts bring together PromptSections into a coherent input for an LLM Service.

---

## Overview

A **Prompt** represents the *final assembled message set* that is passed to the LLM.

It is composed dynamically from one or more **PromptSections** registered in the global
`PromptRegistry`, according to a Service’s `prompt_plan`.

When all components share the same **tuple3 identity** (`origin.bucket.name`),  
the system automatically links them — no manual configuration required.

---

## Components of a Prompt

| Part | Description |
|------|--------------|
| `instruction` | Developer or system message text |
| `message` | User-facing message text |
| `extra_messages` | Optional (role, text) tuples for additional context |
| `metadata` | Optional contextual info for downstream codecs |

---

## Prompt Assembly Flow

1. The **Service** requests a prompt from the `PromptEngine`.
2. The `PromptEngine` loads each **PromptSection** in the service’s `prompt_plan`.
3. Each section contributes an instruction, message, and/or extras.
4. The engine combines them into a single `Prompt` object.
5. The `Prompt` is serialized into structured `LLMRequestMessage` objects.

---

## Default Prompt Resolution

If the Service does not define a `prompt_plan`, the engine automatically looks up
a section whose identity matches the Service’s own identity tuple.

Example:

```
chatlab.standardized_patient.initial
├── GenerateInitialResponseService
├── PatientInitialSection
├── PatientInitialCodec
└── PatientInitialOutputSchema
```

The Service will automatically use `PatientInitialSection` as its prompt source.

---

## Manual Prompt Plans

A Service can override the default by specifying an explicit sequence:

```python
prompt_plan = [
    "chatlab.standardized_patient.initial",
    "chatlab.standardized_patient.followup",
]
```

or using class references:

```python
from chatlab.ai.prompts.sections import PatientInitialSection, PatientFollowupSection

prompt_plan = [PatientInitialSection, PatientFollowupSection]
```

---

## Rendering Process

Each `PromptSection` can define `instruction`, `message`, or dynamic renderers:

```python
class PatientFollowupSection(PromptSection):
    async def arender(self, simulation, **ctx):
        last_symptom = getattr(simulation, "chief_complaint", "none")
        return f"Patient reports continued {last_symptom}."
```

The resulting `Prompt` becomes:

```python
Prompt(
    instruction="You are a standardized patient...",
    message="Patient reports continued sore throat.",
    extra_messages=[],
)
```

---

## Debugging Prompt Assembly

To debug a Service’s prompt composition:

```python
svc = GenerateInitialResponse(simulation_id=1)
prompt = await svc.ensure_prompt(simulation=my_sim)
print(prompt.instruction)
print(prompt.message)
```

To inspect all registered sections:

```python
from simcore_ai.promptkit.registry import PromptRegistry

for ident, section in PromptRegistry._store.items():
    print(ident.to_string(), "→", section.__name__)
```

---

## Integration with PromptEngine

The `PromptEngine` supports both sync and async builds.

```python
prompt = await PromptEngine.abuild_from([PatientInitialSection], context=ctx)
```

Each section receives a context dict:
```python
ctx = {"simulation": simulation, "service": service}
```

Use this context to access runtime state for dynamic rendering.

---

## Best Practices

✅ Keep prompts modular (1 section = 1 narrative purpose)  
✅ Use mixins to share identities across related components  
✅ Limit dynamic logic to renderers — static fields for everything else  
✅ Use consistent tuple3 naming to enable auto‑wiring

---

## Example: Full Prompt Chain

```python
@prompt_section
class PatientInitialSection(PromptSection):
    instruction = "You are a standardized patient in a remote telemed chat."
    message = "Begin naturally and describe your symptoms."


@llm_service
class GenerateInitialResponse(DjangoExecutableLLMService, ChatlabMixin, StandardizedPatientMixin):
    pass
```

This will automatically use the `PatientInitialSection` without needing to specify a `prompt_plan`.

---

## Related Docs

- [Prompt Sections](prompt_sections.md)
- [Services](services.md)
- [Codecs](codecs.md)
- [Schemas](schemas.md)
- [Identity System](identity.md)

---

© 2025 Jackfruit SimWorks • simcore_ai_django
