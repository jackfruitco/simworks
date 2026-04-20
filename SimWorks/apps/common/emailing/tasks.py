"""Async task entrypoints for reusable non-auth transactional email sending."""

from __future__ import annotations

from celery import shared_task

from .service import send_templated_email


@shared_task(bind=True, ignore_result=True)
def send_templated_email_task(
    self,
    recipients: list[str],
    subject: str,
    template_prefix: str,
    context: dict,
    environment_hint: str | None = None,
) -> None:
    send_templated_email(
        to=recipients,
        subject=subject,
        template_prefix=template_prefix,
        context=context,
        environment_hint=environment_hint,
    )
