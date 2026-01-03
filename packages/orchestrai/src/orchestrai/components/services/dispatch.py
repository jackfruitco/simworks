"""Legacy runner dispatch helpers are no longer supported."""

raise ImportError(
    "Service runner dispatch has been removed. Use BaseService.task.run/arun for inline execution."
)
