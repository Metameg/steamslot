import pytest
from fastapi import HTTPException
from limits import parse

from app import rate_limit


def test_enforce_allows_up_to_limit_then_raises_429():
    item = parse("2/minute")
    rate_limit.enforce(item, "k")
    rate_limit.enforce(item, "k")
    with pytest.raises(HTTPException) as exc_info:
        rate_limit.enforce(item, "k")
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_different_identifiers_have_separate_counters():
    item = parse("2/minute")
    rate_limit.enforce(item, "user-a")
    rate_limit.enforce(item, "user-a")
    # user-a is now exhausted; user-b must be unaffected.
    rate_limit.enforce(item, "user-b")
    rate_limit.enforce(item, "user-b")
    with pytest.raises(HTTPException):
        rate_limit.enforce(item, "user-b")


def test_reset_genuinely_clears_counters():
    # Use a window long enough that natural expiry during the test is impossible.
    item = parse("2/minute")
    rate_limit.enforce(item, "reset-me")
    rate_limit.enforce(item, "reset-me")
    with pytest.raises(HTTPException):
        rate_limit.enforce(item, "reset-me")

    rate_limit.reset()

    # If reset() genuinely rebuilt the counters (rather than the window naturally
    # expiring, which cannot happen within this test's runtime for a 1-minute window),
    # this must not raise.
    rate_limit.enforce(item, "reset-me")
    rate_limit.enforce(item, "reset-me")


def test_enforce_never_raises_when_rate_limit_disabled(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        item = parse("2/minute")
        rate_limit.enforce(item, "disabled-key")
        rate_limit.enforce(item, "disabled-key")
        rate_limit.enforce(item, "disabled-key")
        rate_limit.enforce(item, "disabled-key")
    finally:
        get_settings.cache_clear()
