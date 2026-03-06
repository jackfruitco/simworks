# Persistence

Persistence behavior is usually implemented in custom codecs or post-run service hooks.

## Common Patterns

- Persist decoded model output in a codec subclass.
- Persist domain events in `finalize(...)` on service classes.
- Keep persistence idempotent for retry-safe task execution.

## Example Hook

```python
@orca.service
class GenerateReply(..., DjangoBaseService):
    def finalize(self, result, **ctx):
        # write result to DB/log/event stream
        return result
```
