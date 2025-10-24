# Registries — simcore_ai_django

> How identity-aware registries discover and link Services, Codecs, and Prompt Sections.

---

## Overview

Registries map **tuple³ identities** to concrete classes so the framework can wire components automatically. In `simcore_ai_django`, the important registries are:

- **Prompt Registry** — maps identities → `PromptSection` classes.
- **Codec Registry** — maps identities → `DjangoBaseLLMCodec` classes.
- **(Optional) Services Registry** — discovery and collision control for services (dev tooling).

---

## Prompt Registry

**Module:** `simcore_ai.promptkit.registry`

- Populated by the `@prompt_section` decorator.
- Accepts dot-only strings like `"chatlab.standardized_patient.initial"`.
- Used by `PromptEngine` and services to resolve section classes.

```python
from simcore_ai_django.promptkit import PromptRegistry

# Lookup
Section = PromptRegistry.require_str("chatlab.standardized_patient.initial")

# Introspection
all_sections = list(PromptRegistry.all())
```

**Collision Policy:** collisions are resolved via `resolve_collision_django` (DEBUG raises, production suffixes the name).

---

## Codec Registry

**Module:** `simcore_ai_django.codecs.registry`

- Populated by the `@codec` decorator.
- Keys are `(origin, bucket, name)` tuples stored in lowercase snake_case.
- Lookups support exact identity plus fallbacks to `(bucket, "default")` and `("default", "default")` for backwards compatibility.

```python
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.codecs import DjangoCodecRegistry, get_codec

@codec
class PatientInitialCodec(DjangoBaseLLMCodec):
    ...

codec_cls = get_codec("chatlab", "standardized_patient", "initial")
assert codec_cls is PatientInitialCodec
```

**Selection order inside services:**

1. Explicit `codec_class` attribute or injected codec instance.
2. `select_codec()` override return value.
3. `DjangoCodecRegistry.get_codec(origin, bucket, name)` (with fallbacks).
4. Core `simcore_ai.codecs.registry` as a final fallback.
5. Raise `ServiceCodecResolutionError` if nothing matches.

---

## Services Registry (Optional)

If you enable a services registry, it’s typically used to:

- Detect **collisions** early (especially during tests/dev).
- Offer **discovery** (listing available services and identities).
- Power docs or admin UIs.

Pattern:

```python
try:
    from simcore_ai.services.registry import ServiceRegistry
except ImportError:
    ServiceRegistry = None

if ServiceRegistry:
    ServiceRegistry.register(MyService)
    ServiceRegistry.has("chatlab", "standardized_patient", "initial")  # True/False
```

The Django `@llm_service` decorator calls `resolve_collision_django` before registering, mirroring codec/prompt behavior.

---

## Debugging Registries

```python
# Prompt sections
from simcore_ai_django.promptkit import PromptRegistry
print([cls.identity_static().to_string() for cls in PromptRegistry.all()])

# Codecs
from simcore_ai_django.codecs import DjangoCodecRegistry
print(list(DjangoCodecRegistry.names()))
```

Ensure your app imports modules containing decorated classes inside `AppConfig.ready()` so they register on startup.

```python
class ChatlabConfig(AppConfig):
    name = "chatlab"
    def ready(self):
        import chatlab.ai.prompts.sections  # noqa: F401
        import chatlab.ai.codecs           # noqa: F401
        import chatlab.ai.services         # noqa: F401
```

---

## Collision Handling

- Identities are normalized to snake_case.
- Edge-only token stripping applies (class/mixins/app tokens).
- In **DEBUG**, collisions raise to fail fast.
- In **production**, `resolve_collision_django` suffixes the name (`-2`, `-3`, …).

Use the helper directly when you need to preflight identities:

```python
from simcore_ai_django.identity import resolve_collision_django

origin, bucket, name = resolve_collision_django(
    "codec",
    ("chatlab", "standardized_patient", "initial"),
    exists=DjangoCodecRegistry.has,
)
```

---

## Best Practices

- Keep decorator imports under dedicated modules (`ai/services.py`, `ai/codecs.py`, etc.) and import them in `apps.py:ready()`.
- Assert identity alignment in unit tests before registration.
- Prefer dot-only tuple³ identity strings in all references and configuration.

---

© 2025 Jackfruit SimWorks • simcore_ai_django
