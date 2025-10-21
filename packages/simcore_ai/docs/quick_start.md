# Quick Start

This quick start shows how to install `simcore_ai`, register a provider adapter, compose a prompt, and execute a structured service call.

## 1. Install the package

```bash
pip install simcore-ai
```

Optionally install a provider extra:

```bash
pip install simcore-ai[openai]
```

## 2. Configure credentials

Set the environment variables expected by your chosen provider (for example, `OPENAI_API_KEY`). Provider adapters read credentials from environment variables or configuration objects supplied at runtime.

## 3. Create a prompt

```python
from simcore_ai.promptkit import Prompt, PromptSection

system = PromptSection("system", "You are a concise assistant.")
user = PromptSection("user", "Summarize the following article: {title}")

prompt = Prompt([system, user])
messages = prompt.render_to_messages(title="How to build reliable AI workflows")
```

`PromptSection` instances can render templates with variables. `Prompt` converts sections into normalized message objects ready for a provider adapter.

## 4. Define input and output models

```python
from pydantic import BaseModel

class SummaryRequest(BaseModel):
    title: str
    body: str

class SummaryResponse(BaseModel):
    summary: str
```

These models ensure type safety across your service boundary.

## 5. Build a codec and service

```python
from simcore_ai.codecs import JsonCodec
from simcore_ai.services import Service

summary_codec = JsonCodec(SummaryResponse)

summarize_article = Service(
    provider="openai",
    model="gpt-4o-mini",
    codec=summary_codec,
)
```

The codec validates provider responses and converts them into a `SummaryResponse` instance. The service encapsulates provider selection, retry strategy, and telemetry hooks.

## 6. Execute the call

```python
request = SummaryRequest(
    title="Efficient project kickoffs",
    body="...long article body...",
)

response = await summarize_article.call(
    request,
    messages=messages,
)

print(response.summary)
```

Pass the normalized request and prompt messages into the service. `call` returns the typed response defined by your codec.

## 7. Stream results (optional)

```python
async for chunk in summarize_article.stream(request, messages=messages):
    print(chunk.delta)
```

Streaming exposes normalized chunks so you can display partial results or aggregate metrics.

You are now ready to explore advanced topics such as custom tool definitions, multi-turn prompts, and registering new providers. Continue with the [Full Guide](full_documentation.md) for in-depth coverage.
