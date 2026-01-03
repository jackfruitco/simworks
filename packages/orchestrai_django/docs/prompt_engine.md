# Prompt Engine — orchestrai_django

> Compose PromptSections into a single prompt payload for LLM services.

---

## Overview

The **Prompt Engine** takes one or more `PromptSection` classes/instances and produces a `Prompt` object containing:

- `instruction` (developer/system message)
- `message` (user message)
- `extra_messages` (additional role/text pairs)
- `meta` (metadata captured during rendering)

`orchestrai_django` re-exports the core engine from `orchestrai.promptkit`, so the API is identical across both packages.

---

## Core Usage

### Build from sections

```python
from orchestrai_django.components.promptkit import PromptEngine
from chatlab.ai.prompts.sections import PatientInitialSection, PatientFollowupSection

prompt = await PromptEngine.abuild_from(
    PatientInitialSection,
    PatientFollowupSection,
    simulation=my_sim,
    service=my_service,
)
```

- Pass section **classes** or **instances** as positional arguments.
- Context is supplied via keyword arguments (`simulation=...`, `service=...`, etc.).
- The engine instantiates sections, orders them by `weight`, and calls `render_instruction` / `render_message`.

### Incremental composition

```python
engine = PromptEngine()
engine._add_section(PatientInitialSection)
engine._add_section(PatientFollowupSection(weight=50))
prompt = await engine.abuild(simulation=my_sim, service=my_service)
```

- `add()` accepts classes or instances; duplicates are ignored by label.
- Use `.build(...)` for synchronous execution in test scripts (outside event loops).

### Raw prompt

The resulting prompt is a dataclass:

```python
from orchestrai_django.components.promptkit import Prompt

print(prompt.instruction)
print(prompt.message)
print(prompt.extra_messages)
print(prompt.meta.get("sections"))  # labels rendered in order
```

---

## Context Contract

Each section’s `render_instruction` / `render_message` receives the keyword arguments you supply. Common keys:

| Key | Description |
|-----|-------------|
| `simulation` | Active simulation / domain object |
| `service` | Service instance building the prompt |
| `ctx` | Optional additional data you pass |

Sections can opt into any subset of these by signature. The engine never mutates the context you supply.

---

## Error Handling & Tracing

- Rendering happens inside OpenTelemetry spans (`ai.prompt.section`, `ai.prompt.render_instruction`, etc.).
- Exceptions during rendering are caught and logged; the section simply contributes nothing to the prompt.
- Metadata on the returned `Prompt.meta` includes `sections` (labels rendered) and `errors` (render failures).

---

## Integration with Services

`BaseService.ensure_prompt()` (and therefore `DjangoBaseService`) uses `PromptEngine` under the hood:

1. Resolve the service’s `prompt_plan` (list of section specs).
2. Call `PromptEngine.abuild_from(...)` with the resolved classes.
3. Cache the resulting prompt for the lifetime of the service instance.

If a section spec cannot be resolved, the service falls back to Django template rendering via `orchestrai_django.prompts.render_section`.

---

## Custom Engines

`PromptEngine` is a regular class, so you can subclass it for advanced behavior:

```python
from orchestrai_django.components.promptkit import PromptEngine


class CustomPromptEngine(PromptEngine):
    async def abuild(self, **ctx):
        ctx.setdefault("feature_flag", True)
        return await super().abuild(**ctx)
```

Inject your custom engine into a service by overriding `prompt_engine`:

```python
class MyService(DjangoBaseService):
    prompt_engine = CustomPromptEngine
```

---

## Debugging Tips

- Inspect `prompt.meta["errors"]` to see sections that failed to render.
- Use `PromptEngine.add_many()` to bulk load sections from iterables.
- Set `weight` on sections to control ordering (lower weight renders first).

---

© 2025 Jackfruit SimWorks • orchestrai_django
