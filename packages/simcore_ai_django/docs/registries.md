# Registries — simcore_ai_django

> How identity-aware registries discover and link Services, Codecs, and Prompt Sections.

---

## Overview

Registries map **tuple3 identities** to concrete classes so the framework can
wire components automatically. In `simcore_ai_django`, the important registries are:

- **Prompt Registry** — maps identities → `PromptSection` classes
- **Codec Registry** — maps identities → `DjangoBaseLLMCodec` classes
- **(Optional) Services Registry** — discovery and collision control for services (dev tooling)

---

## Prompt Registry

**Module:** `simcore_ai.promptkit.registry`

- Populated by the `@prompt_section` decorator.
- Accepts dot-only strings like `"chatlab.standardized_patient.initial"`.
- Used by `PromptEngine` and Services to resolve section classes.

```python
from simcore_ai.promptkit.registry import PromptRegistry

# Register via decorator
@prompt_section
class PatientInitialSection(PromptSection): ...

# Lookup
Section = PromptRegistry.require_str("chatlab.standardized_patient.initial")

# Introspection
all_sections = list(PromptRegistry.all())
```

**Collision Policy:**  
If two different classes register the same identity:  
- **DEBUG:** raise immediately  
- **Production:** log warning and auto-suffix name (`-2`, `-3`, …) via identity collision resolver.

> Use `Class.identity_tuple()` in tests to assert identities before registration.

---

## Codec Registry

**Module:** `simcore_ai.codecs.registry` (core) and `simcore_ai_django.codecs.registry` (Django)

- Populated by the `@codec` decorator.
- Keys are `(origin, codec_name)` where `codec_name` usually equals `"{bucket}:{name}"` in legacy setups, but **dot-only tuple3** is now preferred.
- Django registry defers to core registry if not found locally.

```python
from simcore_ai_django.api.decorators import codec
from simcore_ai_django.codecs import get_codec as get_django_codec

@codec
class PatientInitialCodec(DjangoBaseLLMCodec): ...

codec = get_django_codec("chatlab", "standardized_patient.initial")  # preferred
```

**Selection Order in Services:**  
1. `codec_class` attribute on service (if set)  
2. `select_codec()` override return (class/instance)  
3. Django registry by identity (`origin`, `bucket.name` or dot tuple3)  
4. Core codec registry as fallback  
5. Raise `ServiceCodecResolutionError`

---

## Services Registry (Optional for dev tooling)

If you enable a services registry, it’s typically used to:
- Detect **collisions** early (especially during tests/dev)
- Offer **discovery** (listing available services and identities)
- Power **docs or admin UIs**

Pattern:

```python
try:
    from simcore_ai.services.registry import ServicesRegistry
except ImportError:
    ServicesRegistry = None

if ServicesRegistry:
    ServicesRegistry.register(MyService)
    ServicesRegistry.has("chatlab", "standardized_patient", "initial")  # True/False
```

---

## Debugging Registries

```python
# Prompt sections
from simcore_ai.promptkit.registry import PromptRegistry
print([s.__name__ for s in PromptRegistry.all()])

# Codecs
from simcore_ai_django.codecs.registry import CODEC_REGISTRY as DJANGO_CODECS
print(list(DJANGO_CODECS.keys()))
```

If registration order matters (e.g., import not executed), ensure your app imports
modules containing decorated classes in `apps.py:ready()`.

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

- Identities are normalized to snake_case
- Edge-only token stripping applied (class/mixins/app tokens)
- In **DEBUG**, collisions raise to fail fast
- In **Production**, `resolve_collision_django` suffixes the name (`-2`, `-3`, …)

Use in registries like:

```python
org, buck, nm = resolve_collision_django(
    kind="prompt_section",
    candidate=("chatlab", "standardized_patient", "initial"),
    exists=lambda t: PromptRegistry.get_str(".".join(t)) is not None,
)
```

---

## Best Practices

- Keep decorator imports under dedicated modules (`ai/services.py`, `ai/codecs.py`, etc.) and import them in `apps.py:ready()`.
- Assert identity alignment in unit tests before registration.
- Prefer dot-only tuple3 identity strings in all references and configuration.

---

© 2025 Jackfruit SimWorks • simcore_ai_django
