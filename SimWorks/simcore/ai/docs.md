SimWorks AI Client — Setup & Usage

This guide shows how to configure and use the new settings‑driven AI client that lives in simcore.ai, with dynamic provider discovery and a clean bootstrap singleton.

⸻

What you get
	•	Single entrypoint: get_ai_client() returns a ready‑to‑use AIClient.
	•	Provider auto‑loading: picks a provider from simcore/ai/providers/<name>.py based on AI_PROVIDER.
	•	Settings/env‑driven config: API keys, base URL, timeouts, and default model come from Django settings (fed by your container env vars).
	•	Per‑call model override: callers can override the model while keeping the provider fixed.
	•	Works everywhere: Django views, ASGI consumers, Celery tasks.

⸻

Directory layout (relevant parts)

simcore/
  ai/
    bootstrap.py          # singleton + provider discovery
    client.py             # AIClient facade
    providers/
      base.py             # ProviderBase (abstract)
      openai.py           # OpenAIProvider + build_from_settings()
    schemas/
      base.py             # AIRequest, AIResponse, AIMessage, StreamChunk, ...


⸻

Prerequisites
	•	Django settings configured from container env variables.
	•	A provider module present under simcore/ai/providers/ that either:
	•	defines a build_from_settings(settings) factory (recommended), or
	•	declares a class that subclasses ProviderBase that the bootstrap can instantiate.

The repo already includes an OpenAI provider: simcore.ai.providers.openai.

⸻

Environment variables → Django settings

Add these (or equivalents) to your container environment:

AI_PROVIDER=openai
AI_DEFAULT_MODEL=gpt-5-mini

# Primary and fallback API keys (either is fine)
OPENAI_API_KEY=sk-...      # preferred for OpenAI
AI_API_KEY=sk-...          # fallback if OPENAI_API_KEY is unset

# Optional; useful for proxies / Azure / compat endpoints
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TIMEOUT_S=45

In settings.py ensure you read them (example):

import os
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")
AI_DEFAULT_MODEL = os.getenv("AI_DEFAULT_MODEL", "gpt-5-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_API_KEY = os.getenv("AI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "45"))


⸻

How provider discovery works

bootstrap.py builds the provider by module name:
	1.	Reads settings.AI_PROVIDER, e.g. "openai".
	2.	Imports simcore.ai.providers.openai dynamically.
	3.	If the module exposes build_from_settings(settings), uses that to construct the provider.
	4.	Otherwise, finds the first class that subclasses ProviderBase and tries to instantiate it with common kwargs.
	5.	Caches the resulting AIClient as a singleton.

OpenAI’s module provides a factory:

# simcore/ai/providers/openai.py

def build_from_settings(settings) -> ProviderBase:
    api_key = getattr(settings, "OPENAI_API_KEY", None) or getattr(settings, "AI_API_KEY", None)
    if not api_key:
        raise RuntimeError("No OpenAI API key found. Please set OPENAI_API_KEY or AI_API_KEY in settings.")
    base_url = getattr(settings, "OPENAI_BASE_URL", None)
    timeout = getattr(settings, "OPENAI_TIMEOUT_S", 30)
    return OpenAIProvider(api_key=api_key, base_url=base_url, timeout=timeout)


⸻

Bootstrap API

# simcore/ai/bootstrap.py

client = get_ai_client()       # returns an AIClient singleton
model  = get_default_model()   # returns settings.AI_DEFAULT_MODEL

Under the hood, this calls init_ai_singleton() which validates AI_PROVIDER and builds the provider instance.

⸻

Minimal usage example (async)

from simcore.ai.bootstrap import get_ai_client, get_default_model
from simcore.ai.schemas.base import AIRequest, AIMessage

async def demo():
    client = get_ai_client()
    req = AIRequest(
        model=get_default_model(),
        messages=[
            AIMessage(role="system", content="You are concise"),
            AIMessage(role="user", content="Give me a 1-sentence fun fact about Laos."),
        ],
        # Optional: extra metadata for logging/analytics
        metadata={"use_case": "chatlab.demo"},
    )
    resp = await client.send_request(req)
    print(resp.messages[-1].content)

With per-call model override

req = AIRequest(
    model="gpt-5.1-mini",  # overrides AI_DEFAULT_MODEL for this call
    messages=[AIMessage(role="user", content="Hello!")],
)


⸻

Streaming usage example

from simcore.ai.schemas.base import AIRequest, AIMessage

async def demo_stream():
    client = get_ai_client()
    req = AIRequest(
        model=get_default_model(),
        messages=[AIMessage(role="user", content="Stream a haiku about field medicine.")],
        stream=True,
    )
    async for chunk in client.stream_request(req):
        if chunk.delta:
            print(chunk.delta, end="")
    print()


⸻

Using it inside a Celery task

# chatlab/ai/tasks.py
from celery import shared_task
from simcore.ai.bootstrap import get_ai_client, get_default_model
from simcore.ai.schemas.base import AIRequest, AIMessage

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def generate_patient_initial(self, simulation_id: int, user_prompt: str):
    import asyncio

    async def _run():
        client = get_ai_client()
        req = AIRequest(
            model=get_default_model(),
            messages=[AIMessage(role="user", content=user_prompt)],
            metadata={"use_case": "chatlab.patient_initial", "simulation_id": simulation_id},
        )
        return await client.send_request(req)

    return asyncio.run(_run())

If your task worker is already running an event loop (e.g., with asgiref), adapt accordingly—don’t nest event loops.

⸻

Error handling patterns

try:
    resp = await client.send_request(req)
except Exception:
    # Log with traceback _and_ propagate so upstream can handle
    import logging
    logging.exception("AI call failed")
    raise

Provider modules should raise provider-specific exceptions that inherit from a common base if you define one (e.g., AITransientError, AIRateLimitedError). Your calling code can catch/retry based on class.

⸻

Testing & local dev
	•	Fake provider: drop fake.py into simcore/ai/providers/ implementing build_from_settings() that returns a ProviderBase producing deterministic responses. Then set AI_PROVIDER=fake.
	•	Unit tests: stub get_ai_client() or monkeypatch build_from_settings to avoid network calls.
	•	Health checks: consider adding a small healthcheck() on your provider to validate credentials at startup.

⸻

Troubleshooting
	•	Unsupported provider: ensure AI_PROVIDER matches a filename (without .py) in simcore/ai/providers/ and isn’t filtered (_ prefix or base).
	•	Missing API key: for OpenAI, either OPENAI_API_KEY or AI_API_KEY must be set; otherwise build_from_settings raises a clear error.
	•	Streaming stalls: verify your reverse proxy permits HTTP/2 or keep‑alive for SSE; check provider’s streaming API limits.
	•	Model not found: confirm the requested model exists for your provider, or just use get_default_model().

⸻

FAQ

Q: Can I switch providers per request?
A: Current design uses a single provider chosen by settings. You can add routing later if needed, but it’s not required for SimWorks now.

Q: Where do I define domain‑specific methods (e.g., generate_patient_initial)?
A: In app‑level connectors (e.g., chatlab/ai/connectors/*) that build an AIRequest, call client.send_request, and normalize to your domain models.

Q: Can I still override the model per use?
A: Yes—pass model="..." to AIRequest; otherwise it uses AI_DEFAULT_MODEL via get_default_model().

⸻

Copy‑paste snippets

Import and call

from simcore.ai.bootstrap import get_ai_client, get_default_model
from simcore.ai.schemas.base import AIRequest, AIMessage

client = get_ai_client()
req = AIRequest(
    model=get_default_model(),
    messages=[AIMessage(role="user", content="Ping")],
)