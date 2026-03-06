# Execution Backends

Services can dispatch work through the built-in task proxy.

## Immediate Dispatch

```python
result_id = MyService.task.enqueue(user_message="hello")
```

## Backend Overrides

```python
result_id = MyService.task.using(backend="celery", queue="priority").enqueue(
    user_message="hello",
)
```

## Async Enqueue

```python
result_id = await MyService.task.using(backend="celery").aenqueue(user_message="hello")
```

## Notes

- Backend configuration is controlled by Django/OrchestrAI settings.
- Task request payloads include rendered instruction text for observability.
