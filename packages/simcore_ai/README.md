# simcore_ai

_A provider-agnostic AI orchestration core for structured LLM workflows._

- **Pure Python** (no Django)
- **PromptKit v3** prompt composition (sections → prompt → messages)
- **Normalized DTOs** for requests/responses/tools/streaming
- **Pluggable providers** (e.g., OpenAI) with schema/tool adapters
- **Service pattern** (class-based or function-decorated)
- **Codec pattern** to attach structured output schemas and validate responses

> If you’re using Django, see the companion glue app `simcore_ai_django` for persistence, signals, audits, and Outbox delivery.

---

## Table of Contents

- [Installation](#installation)
- [Python & Runtime Support](#python--runtime-support)
- [Concepts & Modules](#concepts--modules)
  - [DTOs (`simcore_ai.types`)](#dtos-simcore_aitypes)
  - [PromptKit v3 (`simcore_ai.promptkit`)](#promptkit-v3-simcore_aipromptkit)
  - [Services (`simcore_ai.services`)](#services-simcore_aiservices)
  - [Codecs (`simcore_ai.codecs`)](#codecs-simcore_aicodecs)
  - [Providers (`simcore_ai.providers`)](#providers-simcore_aiproviders)
  - [Schema Compiler & Adapters (`simcore_ai.schemas`)](#schema-compiler--adapters-simcore_aischemas)
- [Adding a Provider](#adding-a-provider)
- [Using the Prompt Engine](#using-the-prompt-engine)
- [Adding Prompt Sections](#adding-prompt-sections)
- [Defining Services & Codecs](#defining-services--codecs)
- [End-to-End Example: Schema + Codec + Service + Call](#end-to-end-example-schema--codec--service--call)
- [Streaming](#streaming)
- [Telemetry & Retries](#telemetry--retries)
- [FAQ](#faq)
- [License](#license)

---

## Installation

Install the core package from PyPI:

```bash
pip install simcore-ai
```

To use the OpenAI provider:

```bash
pip install simcore-ai[openai]
```

For other providers, install their respective extras.

---

## Python & Runtime Support

- Python 3.9+
- Compatible with any asyncio-capable runtime
- Tested on CPython and PyPy

---

## Concepts & Modules

### DTOs (`simcore_ai.types`)

Defines normalized data transfer objects for:

- Requests
- Responses
- Tools
- Streaming chunks

These DTOs standardize interaction across providers and services.

### PromptKit v3 (`simcore_ai.promptkit`)

A composable prompt builder supporting:

- Sections → Prompts → Messages
- Template variables and partial rendering
- Multi-turn conversation support

### Services (`simcore_ai.services`)

Service classes or decorated functions encapsulate AI calls with:

- Typed inputs and outputs
- Optional streaming support
- Retry and telemetry hooks

### Codecs (`simcore_ai.codecs`)

Attach structured output schemas to service responses:

- Validate JSON or text outputs
- Transform raw responses into typed Python objects
- Support for pydantic and custom codecs

### Providers (`simcore_ai.providers`)

Pluggable adapters for AI providers like OpenAI:

- Convert normalized requests to provider-specific calls
- Parse responses back to normalized DTOs
- Support for chat completions, embeddings, etc.

### Schema Compiler & Adapters (`simcore_ai.schemas`)

Compile JSON schemas into codecs and adapters for:

- Input validation
- Output parsing
- Tool integration

---

## Adding a Provider

To add a new AI provider:

1. Implement request and response DTO adapters.
2. Create a provider class implementing the provider interface.
3. Register the provider in `simcore_ai.providers`.

See the OpenAI provider implementation for an example.

---

## Using the Prompt Engine

Build prompts by composing sections:

```python
from simcore_ai.promptkit import Prompt, PromptSection

system_section = PromptSection("system", "You are a helpful assistant.")
user_section = PromptSection("user", "What is the capital of France?")

prompt = Prompt([system_section, user_section])
messages = prompt.to_messages()
```

Pass `messages` to a service call.

---

## Adding Prompt Sections

Create reusable prompt sections with variables:

```python
from simcore_ai.promptkit import PromptSection

template = "Translate the following text to {language}: {text}"
section = PromptSection("translation", template)
rendered = section.render(language="French", text="Hello")
```

---

## Defining Services & Codecs

Define a service with typed input and output:

```python
from pydantic import BaseModel
from simcore_ai.services import Service
from simcore_ai.codecs import JsonCodec

class Input(BaseModel):
    question: str

class Output(BaseModel):
    answer: str

codec = JsonCodec(Output)

service = Service(
    provider="openai",
    model="gpt-4",
    codec=codec,
)

response = await service.call(Input(question="What is 2+2?"))
print(response.answer)  # 4
```

---

## End-to-End Example: Schema + Codec + Service + Call

```python
from pydantic import BaseModel
from simcore_ai.codecs import JsonCodec
from simcore_ai.services import Service

class Question(BaseModel):
    question: str

class Answer(BaseModel):
    answer: str

codec = JsonCodec(Answer)

service = Service(
    provider="openai",
    model="gpt-4",
    codec=codec,
)

input_data = Question(question="What is the capital of Italy?")
response = await service.call(input_data)
print(response.answer)  # Rome
```

---

## Streaming

Services support streaming responses:

```python
async for chunk in service.stream(input_data):
    print(chunk)
```

Streaming chunks are normalized DTOs, enabling consistent handling.

---

## Telemetry & Retries

The core supports telemetry and retry hooks:

- Configure retry policies per service call
- Instrument calls for logging and metrics
- Customize error handling strategies

---

## FAQ

**Q:** Can I use this with Django?  
**A:** Yes, use the companion `simcore_ai_django` app for integration.

**Q:** How do I add a new provider?  
**A:** Implement provider adapters and register them.

**Q:** Does it support embeddings?  
**A:** Yes, through provider-specific adapters.

---

## License

MIT License © 2024 Simcore AI Contributors
