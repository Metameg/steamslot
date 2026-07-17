import time

from fastapi import HTTPException, Request, status
from limits import RateLimitItem, parse
from limits.storage import storage_from_string
from limits.strategies import FixedWindowRateLimiter

from app.config import get_settings

# Module-global storage + limiter, reassignable by reset() for tests. enforce() reads them as
# module globals at call time, so reset()'s reassignment takes effect without rebinding callers.
storage = storage_from_string(get_settings().rate_limit_storage_uri)
limiter = FixedWindowRateLimiter(storage)

# Prod limit definitions. Referenced via `rate_limit.<NAME>` at call time so tests can monkeypatch.
LOGIN_IP: RateLimitItem = parse("10/minute")
LOGIN_EMAIL: RateLimitItem = parse("5/minute")
SIGNUP_IP: RateLimitItem = parse("5/hour")
PURCHASE_USER: RateLimitItem = parse("30/minute")
OPEN_USER: RateLimitItem = parse("30/minute")


def client_ip(request: Request) -> str:
    # MVP: direct client address. Behind a reverse proxy in prod, the real client is in
    # X-Forwarded-For and this returns the proxy IP -- documented limitation, hardened later
    # with a trusted-proxy setting.
    return request.client.host if request.client else "unknown"


def enforce(item: RateLimitItem, *identifiers: str) -> None:
    if not get_settings().rate_limit_enabled:
        return
    if not limiter.hit(item, *identifiers):
        reset_time, _ = limiter.get_window_stats(item, *identifiers)
        retry_after = max(1, int(reset_time - time.time()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(retry_after)},
        )


def reset() -> None:
    """Test helper: wipe all counters by rebuilding the storage from current settings."""
    global storage, limiter
    storage = storage_from_string(get_settings().rate_limit_storage_uri)
    limiter = FixedWindowRateLimiter(storage)
