# packages/simcore_ai/src/simcore_ai/tracing/helpers.py

def flatten_context(context: dict[str, str]) -> dict[str, str]:
    """Flatten `self.context` into trace-friendly attrs as `context.<key>`.

    Values are left as-is when possible; if a value can't be serialized, we
    fall back to `repr(value)`.
    """
    out: dict = {}
    src = context or {}
    for k, v in src.items():
        key = f"context.{k}"
        try:
            out[key] = v
        except Exception:
            out[key] = repr(v)
    return out
