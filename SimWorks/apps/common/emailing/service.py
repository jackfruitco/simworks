"""Thin reusable service for non-auth transactional emails."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .environment import (
    get_email_base_url,
    is_staging_email_context,
)


def _with_staging_subject_prefix(subject: str, is_staging: bool) -> str:
    prefix = str(getattr(settings, "EMAIL_STAGING_SUBJECT_PREFIX", "")).strip()
    if is_staging and prefix and not subject.startswith(prefix):
        return f"{prefix} {subject}"
    return subject


def _build_standard_context(
    context: dict[str, Any] | None,
    *,
    request=None,
    environment_hint: str | None = None,
) -> dict[str, Any]:
    merged = dict(context or {})
    is_staging = environment_hint == "staging" if environment_hint else is_staging_email_context(request)
    merged.setdefault("product_name", "MedSim")
    merged.setdefault("site_name", getattr(settings, "SITE_NAME", "MedSim"))
    merged.setdefault("support_email", getattr(settings, "EMAIL_REPLY_TO", "support@jackfruitco.com"))
    merged["is_staging"] = is_staging
    merged["environment_label"] = "staging" if is_staging else "production"
    merged["email_base_url"] = get_email_base_url(request)
    return merged


def send_transactional_email(
    *,
    to: list[str] | tuple[str, ...],
    subject: str,
    text_body: str,
    html_body: str | None = None,
    from_email: str | None = None,
    reply_to: list[str] | tuple[str, ...] | None = None,
    headers: dict[str, str] | None = None,
    request=None,
    environment_hint: str | None = None,
) -> int:
    is_staging = environment_hint == "staging" if environment_hint else is_staging_email_context(request)
    message = EmailMultiAlternatives(
        subject=_with_staging_subject_prefix(subject, is_staging=is_staging),
        body=text_body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=list(to),
        reply_to=list(reply_to or [settings.EMAIL_REPLY_TO]),
        headers=headers,
    )
    if html_body:
        message.attach_alternative(html_body, "text/html")
    return message.send()


def maybe_send_transactional_email(*, enabled: bool, **kwargs: Any) -> int:
    if not enabled:
        return 0
    return send_transactional_email(**kwargs)


def send_templated_email(
    *,
    to: list[str] | tuple[str, ...],
    subject: str,
    template_prefix: str,
    context: dict[str, Any] | None = None,
    request=None,
    environment_hint: str | None = None,
    headers: dict[str, str] | None = None,
) -> int:
    email_context = _build_standard_context(
        context,
        request=request,
        environment_hint=environment_hint,
    )
    text_body = render_to_string(f"{template_prefix}.txt", email_context)
    html_body = render_to_string(f"{template_prefix}.html", email_context)
    return send_transactional_email(
        to=to,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        headers=headers,
        request=request,
        environment_hint=environment_hint,
    )


def enqueue_templated_email(
    *,
    to: list[str] | tuple[str, ...],
    subject: str,
    template_prefix: str,
    context: dict[str, Any] | None = None,
    environment_hint: str | None = None,
) -> None:
    from .tasks import send_templated_email_task

    task_context = _build_standard_context(context, environment_hint=environment_hint)
    send_templated_email_task.delay(
        list(to),
        subject,
        template_prefix,
        task_context,
        environment_hint,
    )
