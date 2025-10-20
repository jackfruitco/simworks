# Prompt Sections in simcore_ai_django

> PromptSections define the modular building blocks of prompts used by Services.

---

## Overview

A **PromptSection** represents a discrete, reusable component of an LLM prompt.  
Each section defines *what* the AI sees and *why* it’s relevant to the scenario.

> Identity derivation is **Django‑aware** — it automatically uses your app label and mixins — and is **collision‑safe** (duplicate names are suffixed like `-2`, `-3`).

When all prompt components share the same **tuple3 identity** (`origin.bucket.name`),
the framework automatically links them to their matching **Service**, **Codec**, and **Schema**.

---

## Base Class

```python
from simcore_ai_django.api.types import PromptSection
```

`PromptSection` is part of `PromptKit` and provides:
- `instruction`: Developer‑style system instruction (e.g. how the AI should behave)
- `message`: User‑style text (what the AI should respond to)
- Optional async render methods for context‑specific generation

---

## Decorator

```python
from simcore_ai_django.api.decorators import prompt_section
```

The `@prompt_section` decorator:
- Registers the section in the global registry
- Auto‑derives its identity
- Enables `PromptEngine` and `Service` to resolve it automatically

Supports both `@prompt_section` and `@prompt_section(origin="...", bucket="...", name="...")` forms.

---

## Minimal Example

```python
from simcore_ai_django.api.decorators import prompt_section
from simcore_ai_django.api.types import PromptSection

@prompt_section
class PatientInitialSection(PromptSection):
    instruction = "You are a standardized patient in a telemedicine chat."
    message = "Begin the conversation naturally, in first‑person tone."
```

This section registers automatically as `chatlab.standardized_patient.initial` when the app and mixins are configured correctly.

✅ Identity autoderives to `chatlab.standardized_patient.initial`  
(if your app and mixins set `origin` and `bucket` correctly).

---

## Dynamic Prompt Rendering

Sections can override `arender()` to produce context‑aware text dynamically.

```python
@prompt_section
class PatientFollowupSection(PromptSection):
    async def arender(self, simulation, **ctx):
        last_symptom = getattr(simulation, "chief_complaint", "unknown symptoms")
        return f"The patient reports persistent {last_symptom}."
```

```python
def render(self, simulation, **ctx):
    return "Patient continues describing symptoms naturally."
```

You can also define synchronous `render()` if async context isn’t needed.

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
name = "initial"
```

→ `chatlab.standardized_patient.initial`

> Core tokens (`Prompt`, `Section`, `Service`, `Codec`, `Generate`, `Response`, `Mixin`, and `Django`) are automatically stripped when deriving the section name.

---

## Customizing Identity

Optionally override identity manually:

```python
@prompt_section
class CustomPrompt(PromptSection):
    origin = "chatlab"
    bucket = "patient"
    name = "followup"
```

or provide an explicit `identity`:

```python
from simcore_ai.identity import Identity

@prompt_section
class CustomPrompt(PromptSection):
    identity = Identity.from_parts("chatlab", "patient", "followup")
```

---

## Prompt Composition and Plans

Each `Service` may define a **prompt_plan**, a sequence of sections to compose a complete prompt.

```python
prompt_plan = [
    "chatlab.standardized_patient.initial",
    "chatlab.standardized_patient.followup",
]
```

If omitted, the Service automatically uses the PromptSection that matches its own identity.

---

## Prompt Resolution Process

> 0. The identity `(origin, bucket, name)` is resolved using the Django‑aware identity resolver.

1. The `PromptEngine` retrieves section classes from the registry.
2. Each section contributes instruction + message text.
3. Combined prompt → transformed into structured LLM messages:
   - Developer messages from `instruction`
   - User messages from `message`
   - Extras from `extra_messages`

---

## Debugging

```python
from simcore_ai.promptkit.registry import PromptRegistry

# See what’s registered
for ident in PromptRegistry.list_identities():
    print(ident.to_string())
```

`PromptRegistry.list_identities()` provides a safe, public way to view all registered prompt sections.

To confirm identity for your section:

```python
print(PatientInitialSection.identity_tuple())
# ('chatlab', 'standardized_patient', 'initial')
```

---

## Best Practices

✅ Keep `PromptSections` **focused** — one clear role per section  
✅ Prefer static `instruction` + dynamic `message` separation  
✅ Use mixins to simplify identity and avoid repetition  
✅ Avoid hardcoding simulation data — use render hooks instead  
✅ Avoid naming collisions; while the registry automatically suffixes duplicates, prefer unique class names for clarity.

---

## Related Docs

- [Services](services.md)
- [Schemas](schemas.md)
- [Codecs](codecs.md)
- [Prompts](prompts.md)
- [Identity System](identity.md)

---

© 2025 Jackfruit SimWorks • simcore_ai_django
