"""Rate limiting utilities for API endpoints.

This module provides Redis-based rate limiting with a sliding-window algorithm.

Usage:
    @rate_limit(key="ip", limit=5, period=60)
    def my_endpoint(request):
        ...

    @rate_limit(key="user", limit=30, period=60)
    def authenticated_endpoint(request):
        ...
"""

from collections.abc import Callable
from functools import wraps
import hashlib
import time
from typing import Literal

from django.conf import settings
from django.http import HttpRequest
from ninja.errors import HttpError
import redis

RateLimitValue = int | Callable[[], int]


def get_redis_client() -> redis.Redis | None:
    """Get Redis client for rate limiting.

    Uses Redis database 3 (after channels=0, celery broker=1, celery results=2).
    Constructs connection from individual settings to avoid exposing the full
    connection URL, which contains credentials, in the settings namespace.
    """
    hostname = getattr(settings, "REDIS_HOSTNAME", None)
    if not hostname:
        return None

    port = getattr(settings, "REDIS_PORT", 6379)
    password = getattr(settings, "REDIS_PASSWORD", None)
    return redis.Redis(
        host=hostname,
        port=port,
        password=password,
        db=3,
        socket_connect_timeout=2,
    )


def _is_behind_trusted_proxy() -> bool:
    """Return True only when trusted proxy mode is explicitly enabled."""
    value = getattr(settings, "DJANGO_BEHIND_PROXY", False)
    return value is True


def get_client_ip(request: HttpRequest) -> str:
    """Extract the client IP address from the request.

    When DJANGO_BEHIND_PROXY is exactly True, use the rightmost non-empty
    X-Forwarded-For entry, which is expected to be appended by the trusted
    proxy. Otherwise, ignore X-Forwarded-For entirely and use REMOTE_ADDR.
    """
    if _is_behind_trusted_proxy():
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if x_forwarded_for:
            forwarded_chain = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
            if forwarded_chain:
                return forwarded_chain[-1]

    return request.META.get("REMOTE_ADDR") or "unknown"


def get_rate_limit_key(
    request: HttpRequest,
    key_type: Literal["ip", "user", "ip_user"],
    prefix: str,
) -> str:
    """Generate a rate-limit key for the request."""
    parts = [f"ratelimit:{prefix}"]

    if key_type in ("ip", "ip_user"):
        ip = get_client_ip(request)
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
        parts.append(f"ip:{ip_hash}")

    if key_type in ("user", "ip_user"):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            parts.append(f"user:{user.pk}")
        elif key_type == "user":
            ip = get_client_ip(request)
            ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
            parts.append(f"ip:{ip_hash}")

    return ":".join(parts)


class RateLimitExceeded(HttpError):
    """Exception raised when a rate limit is exceeded."""

    def __init__(self, retry_after: int):
        super().__init__(429, "Rate limit exceeded. Please try again later.")
        self.retry_after = retry_after


def check_rate_limit(
    redis_client: redis.Redis,
    key: str,
    limit: int,
    period: int,
) -> tuple[bool, int, int]:
    """Check whether a request is allowed under the sliding-window limit."""
    now = time.time()
    window_start = now - period

    pipe = redis_client.pipeline()

    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    pipe.zadd(key, {f"{now}:{id(now)}": now})
    pipe.expire(key, period + 1)

    results = pipe.execute()
    current_count = results[1]

    if current_count >= limit:
        oldest = redis_client.zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_timestamp = oldest[0][1]
            retry_after = int(oldest_timestamp + period - now) + 1
        else:
            retry_after = period
        return False, current_count, retry_after

    return True, current_count + 1, 0


def _resolve_limit(limit: RateLimitValue) -> int:
    """Resolve a concrete integer rate limit from a value or callable."""
    return limit() if callable(limit) else limit


def resolve_rate_limit_config(config: dict) -> dict:
    """Return a copy of stored rate-limit config with resolved runtime values."""
    return {
        **config,
        "limit": _resolve_limit(config["limit"]),
    }


def rate_limit(
    key: Literal["ip", "user", "ip_user"] = "ip",
    limit: RateLimitValue = 100,
    period: int = 60,
    prefix: str | None = None,
    fail_closed: bool = False,
):
    """Decorator to apply rate limiting to an API endpoint."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            redis_client = get_redis_client()
            if redis_client is None:
                return func(request, *args, **kwargs)

            try:
                redis_client.ping()
            except redis.ConnectionError as exc:
                if fail_closed:
                    raise HttpError(
                        503, "Service temporarily unavailable. Please try again later."
                    ) from exc
                return func(request, *args, **kwargs)

            resolved_limit = _resolve_limit(limit)
            key_prefix = prefix or func.__name__
            rate_key = get_rate_limit_key(request, key, key_prefix)

            is_allowed, _, retry_after = check_rate_limit(
                redis_client,
                rate_key,
                resolved_limit,
                period,
            )

            if not is_allowed:
                raise RateLimitExceeded(retry_after=retry_after)

            return func(request, *args, **kwargs)

        wrapper._rate_limit_config = {
            "key": key,
            "limit": limit,
            "period": period,
            "prefix": prefix,
            "fail_closed": fail_closed,
        }
        return wrapper

    return decorator


def _get_limit(setting_name: str, default: int) -> int:
    """Get a rate-limit value from Django settings or fall back to default."""
    return getattr(settings, setting_name, default)


auth_rate_limit = rate_limit(
    key="ip",
    limit=lambda: _get_limit("RATE_LIMIT_AUTH_REQUESTS", 5),
    period=60,
    prefix="auth",
    fail_closed=True,
)

message_rate_limit = rate_limit(
    key="user",
    limit=lambda: _get_limit("RATE_LIMIT_MESSAGE_REQUESTS", 30),
    period=60,
    prefix="messages",
)

api_rate_limit = rate_limit(
    key="user",
    limit=lambda: _get_limit("RATE_LIMIT_API_REQUESTS", 100),
    period=60,
    prefix="api",
)
