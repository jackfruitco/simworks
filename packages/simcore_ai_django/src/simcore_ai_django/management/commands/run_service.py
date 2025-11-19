# run_service.py
import json
import time
import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.tasks import TaskResultStatus

from simcore_ai.identity import Identity
from simcore_ai.components.services.base import BaseService
from simcore_ai.registry.singletons import get_registry_for


class Command(BaseCommand):
    help = "Enqueue a simcore_ai service by identity and optional context."

    def add_arguments(self, parser):
        # Attempt to provide choices for identity to support shell autocompletion.
        identities: list[str] | None = None
        try:
            registry = get_registry_for(BaseService)
            labels = getattr(registry, "labels", None)
            if callable(labels):
                identities = sorted(labels())
        except Exception:
            identities = None

        identity_kwargs: dict[str, Any] = {
            "type": str,
            "help": "Service identity string (e.g. 'namespace.kind.name').",
        }
        if identities:
            # Providing choices enables shell completion in many environments.
            identity_kwargs["choices"] = identities

        parser.add_argument(
            "identity",
            **identity_kwargs,
        )
        parser.add_argument(
            "-c",
            "--context",
            dest="context",
            type=str,
            default="{}",
            help="JSON-encoded context dict passed to the service "
                 "(e.g. '{\"simulation_id\": 1}').",
        )
        parser.add_argument(
            "--stream",
            dest="stream",
            action="store_true",
            help="Execute service in streaming mode via its `stream_task` instead of the default task.",
        )

    def handle(self, *args, **options):
        # Silence standard logging so only explicit stdout/stderr from this command is shown.
        logging.disable(logging.CRITICAL)
        identity_str: str = options["identity"]
        ctx_raw: str = options["context"]
        use_stream: bool = bool(options.get("stream"))

        # ------------------------------------------------------------------
        # Resolve service class
        # ------------------------------------------------------------------
        Svc = Identity.resolve.try_for_(BaseService, identity_str)
        if Svc is None:
            raise CommandError(f"Could not resolve service for identity: {identity_str!r}")

        ident = Svc.identity.as_str

        self.stdout.write(
            self.style.SUCCESS(
                "Service resolved successfully:\n"
                f"  class:    {Svc.__name__}\n"
                f"  identity: {ident}"
            )
        )

        # ------------------------------------------------------------------
        # Parse context
        # ------------------------------------------------------------------
        try:
            ctx: dict[str, Any] = json.loads(ctx_raw) if ctx_raw else {}
            if not isinstance(ctx, dict):
                raise TypeError(f"context must be a JSON object, got {type(ctx).__name__}")
        except Exception as e:
            raise CommandError(f"Invalid --context JSON: {e}") from e

        if ctx:
            self.stdout.write(f"Context:\n  {ctx!r}")

        # ------------------------------------------------------------------
        # Enqueue task (normal or stream)
        # ------------------------------------------------------------------
        task_attr = "stream_task" if use_stream else "task"
        task_obj = getattr(Svc, task_attr, None)
        if task_obj is None:
            if use_stream:
                raise CommandError(
                    f"Service {Svc.__name__} does not define a 'stream_task'; cannot use --stream."
                )
            raise CommandError(
                f"Service {Svc.__name__} does not define a 'task' attribute; cannot enqueue."
            )

        try:
            result = task_obj.enqueue(ctx=ctx)
        except Exception as e:
            mode = "stream" if use_stream else "standard"
            raise CommandError(f"Failed to enqueue {mode} task for {ident}: {e}") from e

        # Pretty-print TaskResult
        task_id = getattr(result, "id", None)
        status = getattr(result, "status", None)
        backend = getattr(result, "backend", None)
        queue_name = getattr(getattr(result, "task", None), "queue_name", None)

        self.stdout.write(
            self.style.SUCCESS(
                "Task enqueued successfully:\n"
                f"  identity: {ident}\n"
                f"  id:       {task_id}\n"
                f"  status:   {status}\n"
                f"  backend:  {backend}\n"
                f"  queue:    {queue_name}"
            )
        )

        # ------------------------------------------------------------------
        # Wait for completion and pretty-print result
        # ------------------------------------------------------------------
        self._wait_for_result(result, ident=ident)

    def _wait_for_result(self, result, *, ident: str, poll_interval: float = 0.5) -> None:
        """Block until the TaskResult is finished, showing progress, then print a summary.

        If the backend does not support retrieving results, this will print a
        message and return without blocking indefinitely.
        """
        # If the result is already finished (e.g. ImmediateBackend), just print it.
        if getattr(result, "is_finished", False):
            self._pretty_print_result(result, ident=ident)
            return

        self.stdout.write("Waiting for task to finish (Ctrl+C to abort)...")
        self.stdout.flush()

        last_status = None
        try:
            while True:
                try:
                    # Refresh result state from backend.
                    result.refresh()
                except NotImplementedError:
                    self.stdout.write("\nBackend does not support result refresh; cannot wait for completion.\n")
                    return

                status = getattr(result, "status", None)
                attempts = getattr(result, "attempts", None)
                is_finished = getattr(result, "is_finished", False)

                # Print status transitions clearly; otherwise print a dot as a heartbeat.
                if status is not None and status != last_status:
                    status_name = status.name if hasattr(status, "name") else str(status)
                    self.stdout.write(f"\n  status={status_name}, attempts={attempts}")
                    self.stdout.flush()
                    last_status = status
                else:
                    self.stdout.write(".")
                    self.stdout.flush()

                if is_finished:
                    self.stdout.write("\n")
                    break

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            status = getattr(result, "status", None)
            status_name = status.name if hasattr(status, "name") else str(status)
            self.stdout.write(f"\nAborted waiting for task result; latest status={status_name}.\n")
            return

        # Once finished, pretty-print the final result.
        self._pretty_print_result(result, ident=ident)

    def _pretty_print_result(self, result, *, ident: str) -> None:
        """Pretty-print a TaskResult, including timing, attempts, workers, and return value/errors."""
        task_id = getattr(result, "id", None)
        status = getattr(result, "status", None)
        attempts = getattr(result, "attempts", None)
        backend = getattr(result, "backend", None)
        queue_name = getattr(result, "queue_name", None)
        worker_ids = getattr(result, "worker_ids", None) or []
        errors = getattr(result, "errors", None) or []
        enqueued_at = getattr(result, "enqueued_at", None)
        started_at = getattr(result, "started_at", None)
        finished_at = getattr(result, "finished_at", None)

        status_name = status.name if hasattr(status, "name") else str(status)

        duration_str = "-"
        if started_at and finished_at:
            try:
                delta = finished_at - started_at
                duration_str = f"{delta.total_seconds():.3f}s"
            except Exception:
                duration_str = "<unknown>"

        workers_str = ", ".join(worker_ids) if worker_ids else "-"

        # Choose style based on final status: SUCCESSFUL=green, FAILED=red, other=yellow.
        if status == TaskResultStatus.SUCCESSFUL:
            style = self.style.SUCCESS
        elif status == TaskResultStatus.FAILED:
            style = self.style.ERROR
        else:
            style = self.style.WARNING

        self.stdout.write(
            style(
                "Task completed:\n"
                f"  identity:  {ident}\n"
                f"  id:        {task_id}\n"
                f"  status:    {status_name}\n"
                f"  attempts:  {attempts}\n"
                f"  backend:   {backend}\n"
                f"  queue:     {queue_name}\n"
                f"  workers:   {workers_str}\n"
                f"  enqueued:  {enqueued_at}\n"
                f"  started:   {started_at}\n"
                f"  finished:  {finished_at}\n"
                f"  duration:  {duration_str}"
            )
        )

        # Show return value when available
        try:
            return_value = result.return_value
        except Exception as exc:
            return_value = None
            return_repr = f"<unavailable: {exc}>"
        else:
            try:
                return_repr = json.dumps(return_value, indent=2, default=str)
            except TypeError:
                return_repr = repr(return_value)

        self.stdout.write("Return value:\n")
        self.stdout.write(f"{return_repr}\n")

        # Show errors, if any
        if errors:
            self.stdout.write("Errors:\n")
            for idx, err in enumerate(errors, start=1):
                exc_cls = getattr(err, "exception_class", None) or getattr(err, "exception_class_path", None)
                tb = getattr(err, "traceback", None)
                self.stdout.write(f"  [{idx}] {exc_cls}\n")
                if tb:
                    self.stdout.write(f"{tb}\n")