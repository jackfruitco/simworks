simcore/
  ai/
    __init__.py
    client.py           # Provider-agnostic facade (async)
    providers/
      __init__.py
      openai.py         # OpenAI adapter(s)
      # anthropic.py, local_oss.py, etc. later
    prompt_engine/
      v3/               # already exists (keep here)
    schemas/
      base.py           # AIRequest, AIResponse, StreamChunk, ToolCall, Error
    transport/
      http.py           # httpx session mgmt, retries, timeouts
    policies/
      rate_limit.py     # backoff/throttling hooks
      retries.py
    observability/
      tracing.py        # OTel spans, LogFire,
      metrics.py        # token counters, latencies
    utils/
      redact.py         # PHI scrubbing hooks
      idempotency.py