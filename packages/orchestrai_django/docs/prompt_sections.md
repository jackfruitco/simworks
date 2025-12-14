# Prompt Sections in simcore_ai_django

> PromptSections define the modular building blocks of prompts used by Services.

---

## Overview

A **PromptSection** represents a discrete, reusable component of an LLM prompt. Each section defines *what* the AI sees and *why* it’s relevant to the scenario.

> Identity derivation is **Django-aware** and **collision-safe**. Duplicate names are suffixed (`-2`, `-3`, …) in production builds; DEBUG raises immediately.

When all prompt components share the same **tuple³ identity** (`origin.bucket.name`), the framework automatically links them to their matching **Service**, **Codec**, and **Schema**.

---

## Base Class

```python
from simcore_ai_django.api.types import PromptSection
```

`PromptSection` (from `simcore_ai.promptkit`) provides:

- `instruction`: developer/system guidance.
- `message`: user-facing text.
- Optional async render methods for context-specific generation.
- `weight`: ordering hint when multiple sections compose a prompt.

---

## Decorator

```python
from simcore_ai_django.api.decorators import prompt_section
```

The `@prompt_section` decorator:

- Registers the section in the global registry.
- Auto-derives its identity using Django-aware rules.
- Enables `PromptEngine` and services to resolve it automatically.

Supports both `@prompt_section` and `@prompt_section(origin="...", bucket="...", name="...")` forms.

---

## Minimal Example

```python
from simcore_ai_django.api.decorators import prompt_section
from simcore_ai_django.api.types import PromptSection

@prompt_section
class PatientInitialSection(PromptSection):
    instruction = "You are a standardized patient in a telemedicine chat."
    message = "Begin the conversation naturally, in first-person tone."
```

Identity autoderives to `chatlab.standardized_patient.initial` when mixins/app labels supply `origin`/`bucket`.

---

## Dynamic Prompt Rendering

Sections can override render hooks to produce context-aware content:

```python
@prompt_section
class PatientFollowupSection(PromptSection):
    async def render_message(self, simulation, **ctx):
        last_symptom = getattr(simulation, "chief_complaint", "unknown symptoms")
        return f"The patient reports persistent {last_symptom}."
```

You may also implement synchronous `render_message`/`render_instruction`; the engine normalizes both.

---

## Identity and Mixins

```python
from chatlab.ai.mixins import ChatlabMixin, StandardizedPatientMixin

@prompt_section
class PatientInitialSection(PromptSection, ChatlabMixin, StandardizedPatientMixin):
    instruction = "Introduce yourself to the medic."
```

Identity resolves automatically as:

```
origin = "chatlab"
bucket = "standardized_patient"
name   = "initial"
```

> Core tokens (`Prompt`, `Section`, `Service`, `Codec`, `Generate`, `Response`, `Mixin`, plus `"Django"`) are stripped at the edges when deriving the section name.

---

## Customizing Identity

Override identity manually if needed:

```python
@prompt_section
class CustomPrompt(PromptSection):
    origin = "chatlab"
    bucket = "patient"
    name = "followup"
```

or provide an explicit dot identity:

```python
from simcore_ai.identity import Identity

@prompt_section
class CustomPrompt(PromptSection):
    identity = Identity.from_parts("chatlab", "patient", "followup")
```

---

## Prompt Composition and Plans

Each service may define a **prompt_plan**, a sequence of sections (identities or classes) to compose a complete prompt. If omitted, the service automatically uses the section matching its own identity.

---

## Registry Helpers

```python
from simcore_ai_django.components.promptkit import PromptRegistry

print([cls.identity_static().to_string() for cls in PromptRegistry.all()])
SectionCls = PromptRegistry.require_str("chatlab.standardized_patient.initial")
```

Use these helpers to verify registration during startup or tests.

---

## Debugging

```python
print(PatientInitialSection.identity_tuple())
# ('chatlab', 'standardized_patient', 'initial')
```

If a section fails to render, inspect `prompt.meta["errors"]` on the resulting prompt for details.

---

## Best Practices

- Keep `PromptSections` focused — one clear role per section.
- Prefer static `instruction` + dynamic `message` separation.
- Use mixins to simplify identity and avoid repetition.
- Avoid relying on registry suffixes; choose unique class names.

---

## Related Docs

- [Services](services.md)
- [Schemas](schemas.md)
- [Codecs](codecs.md)
- [Prompts](prompts.md)
- [Identity System](identity.md)

---

© 2025 Jackfruit SimWorks • simcore_ai_django
