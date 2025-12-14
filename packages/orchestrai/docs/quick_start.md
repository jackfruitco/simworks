# Quick Start

This quick start demonstrates how to install `simcore_ai`, register a provider client, compose a prompt, and execute a structured request using the normalized client API. The example keeps provider details generic so you can adapt it to your preferred model host.

## 1. Install the package

```bash
pip install simcore-ai
```

Install an optional provider extra if a wheel is available for your target backend:

```bash
pip install simcore-ai[openai]
```

## 2. Configure credentials and register a client

Provide credentials via environment variables (recommended) or pass them directly when creating a client. The client registry stores provider wiring so that services and utility functions can locate a ready-to-use `OrcaClient`.

```python
import os

from simcore_ai.client import create_client_from_dict, get_default_client

create_client_from_dict(
    {
        "backend": "openai",           # or another supported backend key
        "model": "gpt-4o-mini",        # default model for this wiring
        "api_key": os.environ["OPENAI_API_KEY"],
    },
    name="openai-gpt4o",                # optional registry name
    make_default=True,
)

client = get_default_client()
```

The registry fallback (`get_default_client`) lets downstream code resolve the configured provider without coupling to setup logic. If you register multiple clients, set `make_default=True` for the one you want to use implicitly.

## 3. Define request and response models

Structured DTOs keep your application boundary explicit. Requests typically use plain `BaseModel` classes, while structured responses can inherit from `BaseOutputSchema` so codecs can validate outputs automatically.

```python
from pydantic import BaseModel
from simcore_ai.types import BaseOutputSchema

class SummaryRequest(BaseModel):
    title: str
    body: str

class SummaryResponse(BaseOutputSchema):
    summary: str
```

## 4. Compose a prompt

`Prompt` aggregates developer instructions and user-facing content. This example asks the model to return JSON so that the response can be parsed deterministically.

```python
from simcore_ai.promptkit import Prompt

def build_prompt(payload: SummaryRequest) -> Prompt:
    return Prompt(
        instruction="You are a concise assistant that writes executive summaries.",
        message=(
            "Return a JSON object with a 'summary' field that captures the key points of "
            f"the article titled '{payload.title}'.\n\nArticle body:\n{payload.body}"
        ),
    )
```

## 5. Convert the prompt to normalized messages

`OrcaClient` expects a list of `InputItem` objects. The helper below mirrors the conversion performed by `BaseService`.

```python
from simcore_ai.types import InputItem
from simcore_ai.types.content import TextContent


def prompt_to_messages(prompt: Prompt) -> list[InputItem]:
    messages: list[InputItem] = []

    if prompt.instruction:
        messages.append(
            InputItem(
                role="developer",
                content=[TextContent(text=prompt.instruction)],
            )
        )

    if prompt.message:
        messages.append(
            InputItem(
                role="user",
                content=[TextContent(text=prompt.message)],
            )
        )

    for role, text in prompt.extra_messages:
        messages.append(
            InputItem(
                role=role,
                content=[TextContent(text=text)],
            )
        )

    return messages
```

## 6. Execute the request and decode the result

Create a codec to validate the JSON payload, send the request through the client, and convert the response into your typed model.

```python

from simcore_ai.components.codecs.codec import BaseCodec
from simcore_ai.types import Request


class SummaryCodec(BaseCodec):
    name = "summary"
    origin = "guides"
    bucket = "quickstart"
    response_schema = SummaryResponse


summary_codec = SummaryCodec()


async def summarize(payload: SummaryRequest) -> SummaryResponse:
    prompt = build_prompt(payload)
    messages = prompt_to_messages(prompt)

    response = await client.send_request(
        Request(
            model="gpt-4o-mini",
            input=messages,
        )
    )

    structured = summary_codec.validate_from_response(response)
    if structured is None:
        raise ValueError("Model did not return JSON that matches SummaryResponse")

    return structured
```

Wrap the coroutine in `asyncio.run(...)` or integrate it into your existing async workflow.

## 7. Stream responses (optional)

Set `stream=True` on the `Request` and iterate over the asynchronous generator returned by `OrcaClient.stream_request` to process deltas incrementally.

```python
from simcore_ai.types import Request


async def stream_summary(payload: SummaryRequest):
    prompt = build_prompt(payload)
    messages = prompt_to_messages(prompt)

    request = Request(
        model="gpt-4o-mini",
        input=messages,
        stream=True,
    )

    async for chunk in client.stream_request(request):
        print("delta:", chunk.delta)
```

You can now explore advanced topics such as prompt section registries, codec registries, or the service abstractions described in the [Full Guide](full_documentation.md).

