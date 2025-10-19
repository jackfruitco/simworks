# simcore_ai_django Documentation

Welcome to the **simcore_ai_django** documentation — the Django integration layer for the `simcore_ai` AI framework.

This package extends the core `simcore_ai` library to integrate seamlessly with Django apps. It provides decorators, mixins, and base classes to define **AI-driven services**, **codecs**, **prompt sections**, and **response schemas** that can automatically interconnect through a shared identity system.

---

## 📘 Overview

`simcore_ai_django` allows you to:

- Define **LLM services** that can be executed asynchronously or synchronously using `.execute()`.
- Create **PromptSections** that dynamically build LLM prompts.
- Register **Codecs** that validate and persist LLM responses.
- Build **Response Schemas** that validate structured AI outputs.
- Leverage the **Tuple3 Identity System** (`origin.bucket.name`) for automatic wiring of services, codecs, and schemas.
- Extend the **core AI identity system** to Django apps with autoderived origins (from app labels).

---

## 🧩 Core Concepts

### Identity-Driven Architecture

Every major class (service, codec, prompt section, schema) has a **tuple3 identity**:

```
(origin, bucket, name)
```

This identity links corresponding components automatically — for example, a service, codec, and schema that all share the same identity will automatically work together.

See [Identity System](identity.md) for full details.

### Four Pillars

| Component | Purpose | Decorator | Base Class |
|------------|----------|------------|-------------|
| **Service** | Defines an executable AI workflow | `@llm_service` | `DjangoExecutableLLMService` |
| **Codec** | Validates & persists AI responses | `@codec` | `DjangoBaseLLMCodec` |
| **Prompt Section** | Builds prompt content or messages | `@prompt_section` | `PromptSection` |
| **Response Schema** | Defines structured output schema | *(none required)* | `DjangoStrictSchema` |

Each can autoderive its identity, making boilerplate optional.

---

## 📂 Documentation Index

### Getting Started
- [Quick Start Guide](quick_start.md)

### Identity System
- [Tuple3 Identities & Mixins](identity.md)

### Building Blocks
- [Services](services.md)
- [Codecs](codecs.md)
- [Response Schemas](schemas.md)
- [Prompt Sections](prompt_sections.md)
- [Prompts & Prompt Plans](prompts.md)

---

## 🧭 How It Fits Together

Here’s how the main components interact in a typical flow:

```text
Service.execute() 
  → PromptSection.render() builds messages
  → LLM call via Provider
  → Codec.persist() saves results
  → Schema validates structured output
```

Each step is automatically linked by **identity**, so long as the `origin`, `bucket`, and `name` match.

---

## ⚙️ Requirements

- Python 3.11+
- Django 5.0+
- simcore_ai (core library)

---

## 🧩 Related Packages

| Package | Description |
|----------|--------------|
| `simcore_ai` | Core AI utilities and provider abstractions |
| `simcore_ai_django` | Django integration and execution layer |
| `simworks` | Example Django project that consumes this package |

---

## 🧠 Tip
If you’re just starting, begin with the **[Quick Start Guide](quick_start.md)**.  
It walks through creating a complete service (schema → prompt → codec → service) from scratch.

---

© 2025 Jackfruit SimWorks • simcore_ai_django
