# Persistence

Persistence behavior is usually implemented in custom response processors or post-run service hooks.

## Common Patterns

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
