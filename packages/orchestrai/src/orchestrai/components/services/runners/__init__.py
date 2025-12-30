"""Service runners have been removed in favor of inline task execution."""

raise ImportError(
    "Service runners are no longer available; use service.task.run/arun for inline execution."
)
