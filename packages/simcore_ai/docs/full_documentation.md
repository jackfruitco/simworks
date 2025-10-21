# simcore_ai Documentation

This guide explains the concepts, APIs, and extension points that power `simcore_ai`. The framework promotes structured, provider-agnostic AI workflows through normalized data models, composable prompts, codecs, and service abstractions.

## Architecture overview

```
+-----------------+       +-------------------+       +------------------+
| Prompt sections |  -->  | Prompt composition|  -->  | Normalized DTOs  |
+-----------------+       +-------------------+       +------------------+
                                                             |
                                                             v
                                                   +-------------------+
                                                   | Provider adapter  |
                                                   +-------------------+
                                                             |
                                                             v
                                                   +-------------------+
                                                   | Provider response |
                                                   +-------------------+
                                                             |
                                                             v
                                                   +-------------------+
                                                   | Codec validation  |
                                                   +-------------------+
                                                             |
                                                             v
                                                   +-------------------+
                                                   | Typed result      |
                                                   +-------------------+
```

Key building blocks:

- **PromptKit** manages reusable prompt sections and converts them to message DTOs.
- **DTOs** describe requests, responses, tool calls, and streaming chunks in a provider-neutral format.
- **Providers** translate normalized payloads into API calls for a specific large language model service.
- **Codecs** validate and transform provider responses into strongly typed Python objects.
- **Services** combine prompts, codecs, and providers into cohesive units of work.

## DTOs (`simcore_ai.types`)

DTOs standardize cross-provider data exchange. Important classes include:

- `ChatMessage`: Represents a single prompt message with `role`, `content`, and optional metadata.
- `ChatRequest`: Captures model, temperature, and message list for chat completion calls.
- `ChatResponse`: Wraps one or more `ChatChoice` objects returned by the provider.
- `ToolCall` / `ToolResult`: Support tool-enabled workflows where the model requests function invocations.
- `StreamChunk`: Represents incremental responses for streaming scenarios.

DTOs are lightweight `pydantic` models, enabling validation and serialization across async boundaries.

## Prompt composition (`simcore_ai.promptkit`)

PromptKit encourages a layered approach:

1. **Sections** &mdash; `PromptSection` encapsulates reusable content or templates.
2. **Prompt** &mdash; `Prompt` aggregates sections and handles rendering.
3. **Messages** &mdash; `Prompt.render_to_messages(**kwargs)` returns DTOs ready for a provider adapter.

### Section patterns

```python
from simcore_ai.promptkit import Prompt, PromptSection

introduction = PromptSection("system", "You are an assistant that answers concisely.")
question = PromptSection("user", "Answer with a short explanation: {query}")

prompt = Prompt([introduction, question])
messages = prompt.render_to_messages(query="Explain gradient descent")
```

Sections can load content from files, fetch context at runtime, or combine subsections. Because sections render independently, complex prompts remain testable and maintainable.

## Services (`simcore_ai.services`)

A service owns the lifecycle of an AI call: building requests, delegating to providers, and returning typed results. Instantiate `Service` with:

- `provider`: Identifier understood by the provider registry.
- `model`: Provider-specific model name.
- `codec`: Optional codec that validates and transforms responses.
- `config`: Additional options such as retry policies, timeout budgets, or metadata.

### Creating a service

```python
from simcore_ai.codecs import JsonCodec
from simcore_ai.services import Service
from simcore_ai.types import ChatRequest
from pydantic import BaseModel

class KeywordPlan(BaseModel):
    keywords: list[str]

codec = JsonCodec(KeywordPlan)

keyword_service = Service(
    provider="openai",
    model="gpt-4o-mini",
    codec=codec,
    config={"max_retries": 2},
)

request = ChatRequest(messages=messages, temperature=0.2)
plan = await keyword_service.call(request)
```

### Streaming support

Call `Service.stream` to receive `StreamChunk` objects:

```python
async for chunk in keyword_service.stream(request):
    if chunk.choices:
        print(chunk.choices[0].delta)
```

Streaming is helpful for real-time UIs or incremental processing pipelines.

## Codecs (`simcore_ai.codecs`)

Codecs attach structured validation to service outputs. Bundled codecs include:

- `JsonCodec(model_type)`: Parse JSON responses into a `pydantic` model.
- `TextCodec(parser)`: Apply a custom parsing function to raw text output.
- `PassThroughCodec()`: Return the provider response as-is when no transformation is required.

### Creating a custom codec

```python
from simcore_ai.codecs import BaseCodec

class CsvCodec(BaseCodec[list[dict[str, str]]]):
    def decode(self, response):
        rows = []
        for line in response.text.splitlines():
            name, value = line.split(",")
            rows.append({"name": name, "value": value})
        return rows
```

Custom codecs can raise `CodecError` when validation fails, allowing services to trigger retries or error handling logic.

## Provider adapters (`simcore_ai.providers`)

Providers translate normalized DTOs into HTTP calls or SDK invocations. The package ships with adapters for popular API providers; you can register your own adapters via the provider registry.

### Implementing a provider

```python
from simcore_ai.providers import ProviderAdapter, registry
from simcore_ai.types import ChatRequest, ChatResponse

class CustomAdapter(ProviderAdapter):
    name = "acme"

    async def create_chat_completion(self, request: ChatRequest) -> ChatResponse:
        payload = self._convert_request(request)
        raw_response = await self._http_client.post("/v1/chat", json=payload)
        return self._parse_response(raw_response)

registry.register(CustomAdapter())
```

Adapters typically implement methods for chat completions, embeddings, audio, or tools. They can use SDK clients, HTTP libraries, or message buses depending on provider requirements.

## Schema compiler (`simcore_ai.schemas`)

The schema compiler converts JSON Schemas into codecs and tool definitions. Use it to keep your contract definitions in one place.

```python
from simcore_ai.schemas import compile_output_schema

output_schema = {
    "title": "Schedule",
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["tasks"],
}

schedule_codec = compile_output_schema(output_schema)
```

Compiled codecs integrate seamlessly with services, preserving validation guarantees.

## Tool calling

`simcore_ai` supports model-initiated tool invocations. Define tools as functions with type annotations or use DTO-based definitions.

```python
from simcore_ai.tools import Tool
from simcore_ai.types import ToolResult

async def fetch_weather(city: str) -> ToolResult:
    return ToolResult(output=f"Weather for {city}: sunny")

tool = Tool.from_callable("fetch_weather", fetch_weather)
```

Register tools with a service invocation by passing them to the provider call or service configuration. When the model requests a tool, the service executes it and feeds the result back into the conversation.

## Error handling and retries

Services integrate with retry policies specified in `config`. You can provide a retry strategy implementing exponential backoff, circuit breaking, or provider-specific logic.

```python
keyword_service = Service(
    provider="openai",
    model="gpt-4o-mini",
    codec=codec,
    config={
        "max_retries": 3,
        "retryable_exceptions": {"RateLimitError", "TimeoutError"},
    },
)
```

Use telemetry hooks to capture metrics, logging, and tracing details per request.

## Testing services

Because DTOs and codecs are pure Python objects, services are easy to test:

- Replace provider adapters with fakes that return canned DTOs.
- Mock codec outputs to isolate prompt logic.
- Validate prompt rendering by asserting on the messages generated from sections.

```python
class FakeAdapter:
    async def create_chat_completion(self, request):
        return ChatResponse(choices=[...])
```

Inject the fake adapter into the registry during tests to run service logic without hitting external APIs.

## CLI utilities

The package optionally exposes a `simcore-ai` CLI for tasks such as prompt rendering or schema validation. Run `simcore-ai --help` to view available commands once the package is installed with CLI extras.

## Next steps

- Explore the `simcore_ai` source under `src/simcore_ai/` for additional utilities.
- Build specialized codecs for your domain.
- Register multiple providers and route requests dynamically based on performance, latency, or cost.

With these building blocks, you can design resilient AI workflows that remain portable across providers while maintaining strict data contracts.
