"""Rate limiting utilities for API endpoints.

This module provides Redis-based rate limiting with sliding window algorithm.

Usage:
    @rate_limit(key="ip", limit=5, period=60)  # 5 requests per minute per IP
    def my_endpoint(request):
        ...

    @rate_limit(key="user", limit=30, period=60)  # 30 requests per minute per user
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


def get_redis_client() -> redis.Redis:
    """Get Redis client for rate limiting.

    Uses Redis database 3 (after channels=0, celery broker=1, celery results=2).
    """
    redis_base = getattr(settings, "REDIS_BASE", None)
    if redis_base:
        return redis.from_url(f"{redis_base}/3")

    # Fallback for development/testing without Redis
    return None


def get_client_ip(request: HttpRequest) -> str:
    """Extract client IP address from request.

    Handles X-Forwarded-For header for requests behind a proxy.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # Take the first IP in the chain (original client)
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "unknown")
    return ip


def get_rate_limit_key(
    request: HttpRequest,
    key_type: Literal["ip", "user", "ip_user"],
    prefix: str,
) -> str:
    """Generate a rate limit key for the request.

    Args:
        request: The HTTP request
        key_type: Type of key - "ip", "user", or "ip_user" (both)
        prefix: Prefix for the key (usually endpoint name)

    Returns:
        A unique key string for rate limiting
    """
    parts = [f"ratelimit:{prefix}"]

    if key_type in ("ip", "ip_user"):
        ip = get_client_ip(request)
        # Hash the IP for privacy in logs
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
        parts.append(f"ip:{ip_hash}")

    if key_type in ("user", "ip_user"):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            parts.append(f"user:{user.pk}")
        elif key_type == "user":
            # For user-only rate limits, fall back to IP if not authenticated
            ip = get_client_ip(request)
            ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
            parts.append(f"ip:{ip_hash}")

    return ":".join(parts)


class RateLimitExceeded(HttpError):
    """Exception raised when rate limit is exceeded."""

    def __init__(self, retry_after: int):
        super().__init__(429, "Rate limit exceeded. Please try again later.")
        self.retry_after = retry_after


def check_rate_limit(
    redis_client: redis.Redis,
    key: str,
    limit: int,
    period: int,
) -> tuple[bool, int, int]:
    """Check if rate limit is exceeded using sliding window counter.

    Args:
        redis_client: Redis client instance
        key: The rate limit key
        limit: Maximum number of requests allowed
        period: Time period in seconds

    Returns:
        Tuple of (is_allowed, current_count, retry_after_seconds)
    """
    now = time.time()
    window_start = now - period

    pipe = redis_client.pipeline()

    # Remove old entries outside the window
    pipe.zremrangebyscore(key, 0, window_start)

    # Count current entries
    pipe.zcard(key)

    # Add current request with timestamp as score
    pipe.zadd(key, {f"{now}:{id(now)}": now})

    # Set expiry on the key
    pipe.expire(key, period + 1)

    results = pipe.execute()
    current_count = results[1]  # zcard result

    if current_count >= limit:
        # Get the oldest entry to calculate retry_after
        oldest = redis_client.zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_timestamp = oldest[0][1]
            retry_after = int(oldest_timestamp + period - now) + 1
        else:
            retry_after = period
        return False, current_count, retry_after

    return True, current_count + 1, 0


def rate_limit(
    key: Literal["ip", "user", "ip_user"] = "ip",
    limit: int = 100,
    period: int = 60,
    prefix: str | None = None,
):
    """Decorator to apply rate limiting to an API endpoint.

    Args:
        key: Type of rate limit key:
            - "ip": Rate limit by client IP address
            - "user": Rate limit by authenticated user (falls back to IP)
            - "ip_user": Rate limit by both IP and user
        limit: Maximum number of requests allowed in the period
        period: Time period in seconds (default: 60 = 1 minute)
        prefix: Optional prefix for the rate limit key (defaults to function name)

    Returns:
        Decorated function that checks rate limits before execution

    Example:
        @rate_limit(key="ip", limit=5, period=60)
        def login(request, credentials):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            # Get or create Redis client
            redis_client = get_redis_client()

            # If Redis is not available, skip rate limiting (fail open)
            if redis_client is None:
                return func(request, *args, **kwargs)

            try:
                redis_client.ping()
            except redis.ConnectionError:
                # Redis unavailable, fail open
                return func(request, *args, **kwargs)

            # Generate rate limit key
            key_prefix = prefix or func.__name__
            rate_key = get_rate_limit_key(request, key, key_prefix)

            # Check rate limit
            is_allowed, _, retry_after = check_rate_limit(
                redis_client,
                rate_key,
                limit,
                period,
            )

            if not is_allowed:
                raise RateLimitExceeded(retry_after=retry_after)

            # Add rate limit headers to response
            response = func(request, *args, **kwargs)

            return response

        # Store rate limit config for testing/introspection
        wrapper._rate_limit_config = {
            "key": key,
            "limit": limit,
            "period": period,
            "prefix": prefix,
        }

        return wrapper

    return decorator


# Pre-configured rate limiters for common use cases
# Limits are read from Django settings with defaults
def _get_limit(setting_name: str, default: int) -> int:
    """Get rate limit from Django settings or use default."""
    return getattr(settings, setting_name, default)


auth_rate_limit = rate_limit(
    key="ip",
    limit=_get_limit("RATE_LIMIT_AUTH_REQUESTS", 5),
    period=60,
    prefix="auth",
)
message_rate_limit = rate_limit(
    key="user",
    limit=_get_limit("RATE_LIMIT_MESSAGE_REQUESTS", 30),
    period=60,
    prefix="messages",
)
api_rate_limit = rate_limit(
    key="user",
    limit=_get_limit("RATE_LIMIT_API_REQUESTS", 100),
    period=60,
    prefix="api",
)
