# simcore_ai Documentation

`simcore_ai` supplies framework-agnostic building blocks for orchestrating structured LLM workloads. The library focuses on normalized DTOs, composable prompts, codec-driven validation, and reusable service abstractions that sit above provider SDKs.

## Architecture overview

```
+-----------------+       +-------------------+       +------------------+
| Prompt sections |  -->  | Prompt composition|  -->  | Normalized DTOs  |
+-----------------+       +-------------------+       +------------------+
                                                             |
                                                             v
                                                   +-------------------+
                                                   | AIClient          |
                                                   +-------------------+
                                                             |
                                                             v
                                                   +-------------------+
                                                   | Provider adapter  |
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

Key ingredients:

- **PromptKit** builds structured prompts from reusable sections.
- **DTOs** encode prompts, responses, tool calls, and streaming deltas in a provider-neutral format.
- **AIClient** adapts DTOs into provider SDK calls and back again.
- **Codecs** validate responses against `pydantic` schemas.
- **Services** encapsulate prompt rendering, retries, telemetry, and codec selection.

## DTOs (`simcore_ai.types`)

The DTO layer keeps data structures portable across providers:

- `LLMRequestMessage` &mdash; a single prompt turn with `role` and a list of content parts (text, images, tool calls, etc.).
- `LLMRequest` &mdash; the full request envelope: model choice, normalized messages, streaming flag, tool declarations, and codec hints.
- `LLMResponse` &mdash; the normalized result containing response items, usage statistics, provider metadata, and tool call records.
- `LLMResponseItem` &mdash; an assistant turn expressed as structured parts (text chunks, tool outputs, images, audio).
- `LLMStreamChunk` &mdash; incremental streaming deltas emitted while a request is in-flight.
- `BaseOutputSchema` &mdash; base class for typed response contracts that codecs can validate against.

All DTOs inherit from a strict `BaseModel`, so extra fields raise validation errors and serialization stays predictable.

## Prompt composition (`simcore_ai.promptkit`)

PromptKit revolves around two primitives:

- `Prompt` &mdash; a lightweight container for developer instructions, user messages, and optional extra turns.
- `PromptSection` &mdash; declarative components that render text dynamically via `PromptEngine`.

For simple flows, instantiate `Prompt` directly and translate it into request messages:

```python
from simcore_ai.promptkit import Prompt
from simcore_ai.types import LLMRequestMessage, LLMTextPart

prompt = Prompt(
    instruction="You are a concise assistant.",
    message="Reply with JSON containing a 'summary' field for the provided text.",
)

messages: list[LLMRequestMessage] = []

if prompt.instruction:
    messages.append(
        LLMRequestMessage(role="developer", content=[LLMTextPart(text=prompt.instruction)])
    )

if prompt.message:
    messages.append(
        LLMRequestMessage(role="user", content=[LLMTextPart(text=prompt.message)])
    )

for role, text in prompt.extra_messages:
    messages.append(LLMRequestMessage(role=role, content=[LLMTextPart(text=text)]))
```

For reusable, testable prompt sections, subclass `PromptSection` and use `PromptEngine` to render them. In the example below, `payload` represents the request object carrying runtime data (for example, an instance of `SummaryRequest`).

```python
from simcore_ai.promptkit import PromptEngine, PromptSection
from simcore_ai.identity import Identity

class SystemSection(PromptSection):
    identity = Identity.from_parts("guides", "summaries", "system")
    instruction = "You are a concise assistant."  # static content

class ArticleSection(PromptSection):
    identity = Identity.from_parts("guides", "summaries", "article")

    async def render_message(self, *, title: str, body: str, **_: object) -> str | None:
        return (
            "Return JSON with a 'summary' field for the article titled "
            f"'{title}'.\n\nArticle body:\n{body}"
        )

prompt = await PromptEngine.abuild_from(SystemSection, ArticleSection, title=payload.title, body=payload.body)
```

The resulting `Prompt` can be converted to `LLMRequestMessage` instances using the helper shown above.

## Codecs (`simcore_ai.codecs`)

Codecs transform normalized responses into typed models. Subclass `BaseLLMCodec` or decorate a class with `@codecs.codec` to register it.

```python
from simcore_ai.codecs import BaseLLMCodec
from simcore_ai.types import BaseOutputSchema

class KeywordPlan(BaseOutputSchema):
    keywords: list[str]

class KeywordCodec(BaseLLMCodec):
    name = "keyword-plan"
    origin = "guides"
    bucket = "services"
    schema_cls = KeywordPlan

codec = KeywordCodec()

structured = codec.validate_from_response(response)
if structured is None:
    raise ValueError("Response did not contain JSON matching KeywordPlan")
```

`validate_from_response` extracts structured JSON from the normalized response, validates it against `schema_cls`, and returns an instance of that schema. If validation fails, `None` is returned so you can fall back to manual parsing or trigger a retry.

## Provider clients (`simcore_ai.client`)

The client registry wires provider configuration to reusable `AIClient` instances.

```python
import os

from simcore_ai.client import create_client_from_dict, get_default_client

create_client_from_dict(
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": os.environ["OPENAI_API_KEY"],
    },
    name="openai-gpt4o",
    make_default=True,
)

client = get_default_client()
```

Send requests using normalized DTOs:

```python
from simcore_ai.types import LLMRequest

request = LLMRequest(model="gpt-4o-mini", messages=messages)
response = await client.send_request(request)
```

For streaming, set `stream=True` on the request and iterate over `client.stream_request(request)`.

## Services (`simcore_ai.services`)

`BaseLLMService` wraps prompt rendering, codec selection, retries, telemetry, and event emission around an `AIClient`. Services expect two collaborators:

- a **simulation** object carrying runtime context (at minimum an `id` attribute)
- a **ServiceEmitter** implementation that records requests, responses, failures, and streaming chunks

### Subclassing `BaseLLMService`

```python
from dataclasses import dataclass

from simcore_ai.client import get_default_client
from simcore_ai.promptkit import Prompt
from simcore_ai.services import BaseLLMService
from simcore_ai.types import LLMRequestMessage, LLMTextPart

# reuse `codec = KeywordCodec()` from the codecs section above

class ConsoleEmitter:
    def emit_request(self, simulation_id, identity, request):
        print("request", identity, request.model)

    def emit_response(self, simulation_id, identity, response):
        print("response", identity)

    def emit_failure(self, simulation_id, identity, correlation_id, error):
        print("failure", identity, error)

    def emit_stream_chunk(self, simulation_id, identity, chunk):
        print("chunk", identity, chunk.delta)

    def emit_stream_complete(self, simulation_id, identity, correlation_id):
        print("stream complete", identity)


class KeywordService(BaseLLMService):
    origin = "guides"
    bucket = "services"
    name = "keyword"
    provider_name = "openai"  # resolved by client registry

    def select_codec(self):
        return codec  # return an instance or class of BaseLLMCodec

    async def build_request_messages(self, simulation) -> list[LLMRequestMessage]:
        prompt = Prompt(
            instruction="You return keyword lists as JSON.",
            message=f"Reply with {{\"keywords\": [...]}} for: {simulation.text}",
        )

        messages: list[LLMRequestMessage] = []
        if prompt.instruction:
            messages.append(LLMRequestMessage(role="developer", content=[LLMTextPart(text=prompt.instruction)]))
        if prompt.message:
            messages.append(LLMRequestMessage(role="user", content=[LLMTextPart(text=prompt.message)]))
        return messages


@dataclass
class Simulation:
    id: int
    text: str


service = KeywordService(
    simulation_id=42,
    emitter=ConsoleEmitter(),
    client=get_default_client(),
)

simulation = Simulation(id=42, text="Launch a self-serve workspace tier for startups.")
response = await service.run(simulation)
structured = codec.validate_from_response(response)
```

`run` executes a single request with retries. To stream provider deltas, call `await service.run_stream(simulation)`; streaming chunks are forwarded to the emitter.

### Function services with `llm_service`

The `llm_service` decorator turns an async function into a service class. This is useful when you want to bundle prompt rendering with side effects in a single coroutine.

```python
from simcore_ai.services import llm_service

@llm_service(origin="guides", bucket="summaries", name="article")
async def on_summary_complete(simulation, slim):
    print("completed", simulation.id)

SummaryService = on_summary_complete  # decorator returns the generated subclass
```

The generated class still expects an emitter and simulation context; only the lifecycle hooks are auto-wired.

## Streaming

- **Direct client streaming** &mdash; set `stream=True` on `LLMRequest` and consume `AIClient.stream_request(request)` to receive `LLMStreamChunk` items as soon as the provider produces them.
- **Service streaming** &mdash; call `await service.run_stream(simulation)` to let the service orchestrate streaming, retries, and telemetry; streaming data is pushed through the configured emitter.

Each stream chunk exposes `delta` (text), optional `tool_call_delta`, and incremental usage metadata.

## Schema adapters (`simcore_ai.schemas`)

Schema adapters let you tweak JSON Schemas per provider before they are embedded in requests.

```python
from simcore_ai.schemas import register_adapter, schema_adapter, compile_schema

@schema_adapter("openai", order=50)
def enforce_object(adapter_schema: dict) -> dict:
    schema = dict(adapter_schema)
    schema.setdefault("type", "object")
    return schema

compiled = compile_schema(raw_schema, provider="openai")
```

Adapters run in ascending `order`, allowing you to compose provider-specific adjustments.

## Tool metadata (`simcore_ai.types.tools`)

Declare tool contracts with `BaseLLMTool` and attach them to `LLMRequest.tools`. Streaming tool call progress is captured via `LLMToolCallDelta`.

```python
from simcore_ai.types import BaseLLMTool

search_tool = BaseLLMTool(
    name="search",
    description="Look up articles in the knowledge base",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)

request.tools.append(search_tool)
request.tool_choice = "auto"
```

When the provider triggers a tool call, the normalized response includes `LLMToolCall` entries so your application can execute the requested function and feed results back into the conversation.

## Testing

Because services operate on DTOs and dependency injection, unit testing stays straightforward:

- Inject a fake `AIClient` that returns canned `LLMResponse` objects.
- Provide a lightweight emitter that records emitted events for assertions.
- Assert on prompt rendering by calling your helper that converts prompts into `LLMRequestMessage` lists.

```python
from simcore_ai.types import LLMResponse

class FakeClient:
    async def send_request(self, request):
        return LLMResponse(outputs=[], usage=None)

fake_service = KeywordService(
    simulation_id=1,
    emitter=ConsoleEmitter(),
    client=FakeClient(),
)

await fake_service.run(Simulation(id=1, text="Example payload"))
```

## Next steps

- Explore the source under `src/simcore_ai/` for additional utilities such as tracing helpers and decorators.
- Register multiple clients and experiment with routing based on latency or cost.
- Build custom codecs to validate domain-specific response formats.
- Combine tool declarations with schema adapters to create robust, provider-agnostic tool-calling workflows.

With these primitives, you can construct resilient AI workflows that remain portable across providers while preserving strong data contracts.

