# Execution Backends

Services can dispatch work through the built-in task proxy.

## Default Dispatch (Celery)

```python
result_id = MyService.task.enqueue(user_message="hello")
```

By default, calls are queued to Celery workers.

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

## Immediate Dispatch Override

```python
result_id = MyService.task.using(backend="immediate").enqueue(user_message="hello")
```

## Notes

- Backend configuration is controlled by Django/OrchestrAI settings.
- Task request payloads include rendered instruction text for observability.
