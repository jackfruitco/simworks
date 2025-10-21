# simcore_ai_django Documentation

Welcome to the **simcore_ai_django** documentation — the Django integration layer for the `simcore_ai` AI framework.

This package extends the core `simcore_ai` library so Django apps can register AI services, codecs, prompt sections, and response schemas that cooperate automatically via shared tuple³ identities.

---

## 📘 Overview

`simcore_ai_django` allows you to:

- Define **LLM services** that can be executed synchronously or asynchronously through `.execute()` and `.enqueue()`.
- Create **PromptSections** that render developer and user-facing messages.
- Register **Codecs** that validate and persist LLM responses using Django models.
- Build **Response Schemas** with strict Pydantic models (`DjangoBaseOutputSchema`).
- Leverage the **Tuple³ Identity System** (`origin.bucket.name`) for automatic wiring.
- Extend the **core AI identity system** with Django-aware defaults (app labels, mixins, strip tokens).

---

## 🧩 Core Concepts

### Identity-Driven Architecture

Every major class (service, codec, prompt section, schema) has a tuple³ identity:

```
(origin, bucket, name)
```

Matching identities allow components to discover one another automatically. See [Identity System](identity.md) for full details.

### Four Pillars

| Component | Purpose | Decorator | Base Class |
|-----------|---------|-----------|------------|
| **Service** | Defines an executable AI workflow | `@llm_service` | `DjangoExecutableLLMService` |
| **Codec** | Validates & persists AI responses | `@codec` | `DjangoBaseLLMCodec` |
| **Prompt Section** | Builds prompt content or messages | `@prompt_section` | `PromptSection` |
| **Response Schema** | Defines structured output schema | *(decorator optional)* | `DjangoBaseOutputSchema` |

Each component can autoderive its identity, keeping boilerplate minimal.

---

## 📂 Documentation Index

### Getting Started
- [Quick Start Guide](quick-start.md)

### Identity System
- [Tuple³ Identities & Mixins](identity.md)

### Building Blocks
- [Services](services.md)
- [Codecs](codecs.md)
- [Response Schemas](schemas.md)
- [Prompt Sections](prompt_sections.md)
- [Prompts & Prompt Plans](prompts.md)
- [Prompt Engine](prompt_engine.md)

### Platform Integration
- [Execution Backends](execution_backends.md)
- [Registries](registries.md)
- [Signals & Emitters](signals.md)
- [Settings](settings.md)

---

## 🧭 How It Fits Together

A typical flow looks like:

```text
Service.execute()
  → PromptSection.render_* builds messages
  → LLM call via provider
  → Codec.persist() validates & saves
  → Schema enforces structured output
```

Each step is linked by **identity** so long as the `origin`, `bucket`, and `name` match.

---

## ⚙️ Requirements

- Python 3.11+
- Django 5.0+
- `simcore_ai`

---

## 🧩 Related Packages

| Package | Description |
|---------|-------------|
| `simcore_ai` | Core AI utilities and provider abstractions |
| `simcore_ai_django` | Django integration and execution layer |
| `simworks` | Example Django project that consumes this package |

---

## 🧠 Tip

If you’re just starting, begin with the **[Quick Start Guide](quick-start.md)**. It walks through creating a complete chain (schema → prompt section → codec → service).

---

© 2025 Jackfruit SimWorks • simcore_ai_django
