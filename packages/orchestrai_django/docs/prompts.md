# Prompts and Prompt Plans in orchestrai_django

> Prompts assemble PromptSections into the final input for an LLM service.

---

## Overview

A **Prompt** represents the final set of messages sent to the LLM. Services build prompts dynamically from one or more `PromptSection`s resolved by identity or declared in a `prompt_plan`.

When components share the same **tuple³ identity** (`origin.bucket.name`), the system links them automatically — no manual wiring required.

---

## Prompt Composition

1. The **Service** asks `PromptEngine` to build a prompt.
2. The engine instantiates each `PromptSection` in the service’s `prompt_plan` (or the section matching the service identity).
3. Sections emit instructions/messages; the engine merges them into a single `Prompt` dataclass.
4. The service converts that prompt into structured `InputItem` objects.

---

## Default Prompt Resolution

If a service does not define `prompt_plan`, the engine looks up a section whose identity matches the service’s own tuple.

Example chain:

```
chatlab.standardized_patient.initial
├── GenerateInitialResponseService
├── PatientInitialSection
├── PatientInitialCodec
└── PatientInitialOutputSchema
```

The service automatically uses `PatientInitialSection` as its prompt source.

---

## Manual Prompt Plans

A service can override the default by providing explicit specs:

```python
prompt_plan = [
    "chatlab.standardized_patient.initial",
    "chatlab.standardized_patient.followup",
]
```

You can also provide classes directly:

```python
from chatlab.ai.prompts.sections import PatientInitialSection, PatientFollowupSection

prompt_plan = [PatientInitialSection, PatientFollowupSection]
```

Each spec is resolved via `orchestrai.promptkit.resolvers.resolve_section`, so canonical strings or classes both work.

---

## Inspecting Prompts at Runtime

```python
svc = GenerateInitialResponse(simulation_id=1)
prompt = await svc.ensure_prompt(simulation=my_sim)

print(prompt.instruction)
print(prompt.message)
print(prompt.extra_messages)
print(prompt.meta["sections"])  # labels rendered in order
```

`ensure_prompt` caches the prompt on the service instance for reuse during the request lifecycle.

---

## Working with PromptRegistry

```python
from orchestrai_django.components.promptkit import PromptRegistry

sections = [cls.__name__ for cls in PromptRegistry.all()]
print(sections)
```

Use `PromptRegistry.require_str("origin.bucket.name")` to fetch a specific section class by identity.

---

## Rendering Hooks

Each `PromptSection` can define `instruction`, `message`, or override `render_instruction` / `render_message` for dynamic content:

```python
@prompt_section
class PatientFollowupSection(PromptSection):
    async def render_message(self, simulation, **ctx):
        last_symptom = getattr(simulation, "chief_complaint", "none")
        return f"Patient reports continued {last_symptom}."
```

The engine passes keyword arguments such as `simulation` and `service` to these methods.

---

## Debugging Tips

- Print `PromptRegistry.all()` to verify sections were registered during startup.
- Check `prompt.meta["errors"]` for sections that failed to render.
- Weight sections via the `weight` attribute to control ordering (lower renders first).

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

This service will automatically render `PatientInitialSection` without specifying a `prompt_plan` because the identities align.

---

## Related Docs

- [Prompt Sections](prompt_sections.md)
- [Prompt Engine](prompt_engine.md)
- [Services](services.md)
- [Codecs](codecs.md)
- [Schemas](schemas.md)
- [Identity System](identity.md)

---

© 2025 Jackfruit SimWorks • orchestrai_django
