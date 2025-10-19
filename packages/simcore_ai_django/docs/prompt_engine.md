# Prompt Engine — simcore_ai_django

> The Prompt Engine orchestrates prompt composition, rendering, and delivery to the LLM.

---

## Overview

The **Prompt Engine** is the layer that takes:
1. A **Service's** `prompt_plan` or matching `PromptSection`
2. A **Simulation** or runtime context
3. Produces a **structured prompt** ready for the LLM provider

It connects your declarative `PromptSection` definitions to the actual `LLMRequestMessage` objects
that form the model's input.

---

## Responsibilities

| Role | Description |
|------|--------------|
| **Resolve Sections** | Find matching `PromptSection` classes via registry or identity |
| **Render** | Execute static or dynamic section instructions/messages |
| **Assemble** | Combine them into a structured `Prompt` |
| **Transform** | Convert to provider-compatible `LLMRequestMessage` list |
| **Trace** | Annotate spans for performance and debugging |

---

## Core Entry Points

### 1️⃣ Build Prompt from Service Identity

```python
from simcore_ai_django.api.prompt_engine import PromptEngine

prompt = await PromptEngine.abuild_for_service(MyService, simulation=my_sim)
```

- Looks up sections by service identity.
- Falls back to `service.prompt_plan` if defined.
- Calls `arender()` on dynamic sections.

### 2️⃣ Build from Explicit Section List

```python
from chatlab.ai.prompts.sections import PatientInitialSection, PatientFollowupSection
prompt = await PromptEngine.abuild_from([PatientInitialSection, PatientFollowupSection], context={"simulation": my_sim})
```

### 3️⃣ Synchronous Build (for testing)

```python
prompt = PromptEngine.build_for_service(MyService, simulation=my_sim)
```

---

## Prompt Composition

The engine merges multiple `PromptSection`s into a unified `Prompt` object:

```python
Prompt(
    instruction="You are a standardized patient in a telemedicine chat.",
    message="Begin the conversation naturally.",
    extra_messages=[
        {"role": "system", "content": "Follow role guidelines."},
        {"role": "user", "content": "Reply in first-person tone."},
    ],
)
```

Each section contributes one or more of these fields.

---

## Context Injection

When rendering, each section’s `arender()` or `render()` method receives the following context:

| Key | Description |
|-----|--------------|
| `simulation` | The active simulation object |
| `service` | The current service class or instance |
| `ctx` | Any additional context passed by the caller |

You can override these arguments in your Service:

```python
async def get_prompt_context(self, simulation):
    return {"simulation": simulation, "user": simulation.user}
```

---

## Identity Resolution Flow

1. Service identity derived via Django rules (app → bucket → name)
2. Engine queries `PromptRegistry` for matching sections
3. If none found, raises `PromptSectionNotFoundError`
4. Otherwise, assembles sections in order

Example:
```
chatlab.standardized_patient.initial
├── Service: GenerateInitialResponse
├── Prompt: PatientInitialSection
├── Codec: PatientInitialCodec
└── Schema: PatientInitialOutputSchema
```

---

## Prompt Registry Integration

The engine interacts with:

```python
from simcore_ai.promptkit.registry import PromptRegistry
```

to retrieve registered `PromptSection` classes.  
All sections are registered automatically by the `@prompt_section` decorator.

```python
PromptRegistry.find(("chatlab", "standardized_patient", "initial"))
```

---

## Debugging Prompts

### Dump Prompt Plan

```python
prompt = await PromptEngine.abuild_for_service(MyService, simulation=my_sim)
prompt.debug_dump()
```

### Inspect Section Timing

Enable `SIMCORE_AI_DEBUG=True` to measure section render times:

```
[PromptEngine] render: PatientInitialSection → 25ms
```

---

## Extending PromptEngine

You can subclass or monkey-patch behavior safely:

```python
from simcore_ai_django.promptkit.engine import PromptEngine

class CustomPromptEngine(PromptEngine):
    @classmethod
    async def abuild_for_service(cls, service_cls, simulation, **ctx):
        ctx["custom"] = True
        return await super().abuild_for_service(service_cls, simulation, **ctx)
```

Then set in your app’s `apps.py`:

```python
from chatlab.ai.prompt_engine import CustomPromptEngine

PromptEngine.set_default(CustomPromptEngine)
```

---

## Error Handling

| Error | Description |
|:------|:-------------|
| `PromptSectionNotFoundError` | No section found matching service identity |
| `PromptRenderError` | Section raised an exception during `arender()` |
| `PromptAssemblyError` | Internal failure assembling prompt text |

When in **DEBUG** mode, these errors raise immediately; in production, they are logged and a fallback prompt is used.

---

## Summary

✅ Automatically assembles structured LLM prompts  
✅ Identity-aware section resolution  
✅ Async‑safe rendering pipeline  
✅ Integrates with tracing, registries, and services  

---

© 2025 Jackfruit SimWorks • simcore_ai_django
