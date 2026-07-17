# Rate Limiting + Login Timing-Oracle Fix — Implementation Plan (Slice 3)

## Context

The HTTP + auth slice shipped `/auth/login`, `/auth/signup`, and the money endpoints
(`/packs/purchase`, `/packs/{id}/open`) as real, reachable HTTP routes — but with **no throttling
of any kind**. On a real-money app that's a live gap: `/auth/login` and `/auth/signup` are
unauthenticated and state-changing, so they're open to password brute-forcing, mass bot signups,
and account enumeration. That slice's own final review promoted one specific finding to the top of
this slice's queue: `auth_service.login` (`app/services/auth_service.py:62`) **skips the
deliberately-slow argon2 verify entirely when the email is unknown** (`user is None or
user.password_hash is None` short-circuits before `verify_password`), so absent-account logins
return measurably faster than wrong-password ones — a usable email-enumeration **timing oracle**
that raw rate limiting alone does not close.

This slice adds **Redis-backed rate limiting** to the auth and money endpoints and **fixes the
login timing oracle**. It deliberately does **not** add account lockout/backoff, CAPTCHA, or
global/read-endpoint limiting — those are later hardening work.

## Locked Decisions

- **Counter store: Redis** (a new `redis` service in the existing docker-compose). Counters survive
  restarts/deploys and are shared across app instances. **Tests use in-process `memory://` storage**
  (via the `limits` library) so the suite needs no Redis at all.
- **Library: `limits`** (the maintained core that slowapi wraps) used **directly**, not slowapi.
  Reason: per-account (per-email) login limiting needs the request body, which slowapi's
  decorator/key-func model can't cleanly see; a direct `limits` call inside the handler is simpler
  and gives one consistent mechanism for per-IP, per-email, and per-user keys.
- **Scope: rate limiting + the timing-oracle fix.** No lockout/backoff, no CAPTCHA, no global or
  read-endpoint limits this slice.

## Global Constraints (carried forward — still binding)

- Money is integer cents; `ledger_entries` is source of truth; services flush only, `get_db` owns
  the transaction. **This slice touches none of that** — rate-limit checks happen before any DB
  write and raise `HTTPException(429)` (a native FastAPI exception) before the service layer runs.
- Never store raw secrets. (Unchanged; the timing fix reuses the existing argon2 helpers.)

## What Gets Limited (and what doesn't)

| Endpoint | Key(s) | Rough prod limit | Why |
|---|---|---|---|
| `POST /auth/login` | per-IP **and** per-email | IP 10/min, email 5/min | brute force + targeted brute force |
| `POST /auth/signup` | per-IP | 5/hour | bot/mass account creation |
| `POST /packs/purchase` | per-user | 30/min | abuse / DB-load guard |
| `POST /packs/{id}/open` | per-user | 30/min | abuse / DB-load guard |

Login checks **both** dimensions (429 if *either* is exceeded): per-IP throttles one source hitting
many accounts; per-email throttles a distributed attack rotating IPs against one account.

**Not limited this slice:** the Stripe webhook (doesn't exist yet; when it does it's protected by
signature verification, not throttling), read endpoints (`/me`, `/wallet/balance`, `/packs/types`,
`/packs/pulls`), and `/auth/logout`. Global/read limiting and lockout are future work.

## Existing Code To Reuse

- `app/security/password.py`: `hash_password`, `verify_password` — the timing fix builds a dummy
  argon2 hash with `hash_password` and burns a `verify_password` call on the absent-user path.
- `app/api/deps.py`: `get_current_user` — the per-user money-endpoint limit is a dependency that
  depends on it (FastAPI caches it within the request, so no double lookup).
- `app/config.py` `Settings` (+ `get_settings()` lru_cache), `app/main.py`, `app/api/v1/auth.py`,
  `app/api/v1/packs.py`, `tests/conftest.py` — all modified as below.

## New / Modified Files

```
backend/app/rate_limit.py         # NEW — storage, limiter, enforce(), reset(), limit items, deps
backend/app/config.py             # + rate_limit_storage_uri, rate_limit_enabled
backend/app/services/auth_service.py  # login: constant-work path (timing fix)
backend/app/api/v1/auth.py        # login: per-IP + per-email enforce; signup: per-IP dep
backend/app/api/v1/packs.py       # purchase/open: per-user limit dep
backend/tests/conftest.py         # + autouse reset_rate_limits fixture
backend/docker-compose.yml        # + redis service
backend/.env.example              # + RATE_LIMIT_STORAGE_URI
backend/pyproject.toml            # + limits, redis
```

---

## Task Breakdown (each TDD, independently reviewable)

### Task 1 — Rate-limit infrastructure
**Files:** `app/rate_limit.py` (new), `app/config.py`, `docker-compose.yml`, `.env.example`,
`pyproject.toml`, `tests/conftest.py`; test `tests/test_rate_limit_core.py`.

Add deps `limits>=3` and `redis>=5` to `pyproject.toml`; `uv sync`.

Add to `Settings` (`config.py`): `rate_limit_storage_uri: str = "memory://"` (default is in-process
memory — so the test suite and any no-config run need no Redis; dev/prod override via env) and
`rate_limit_enabled: bool = True` (ops kill-switch).

`app/rate_limit.py`:
```python
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
```
(Note: `enforce` must reference the module globals `limiter`/`storage`, and handlers must reference
the limit items as `rate_limit.LOGIN_IP` etc. — see Tasks 3/4 — so `reset()` and monkeypatch both
take effect.)

`docker-compose.yml` — add alongside `postgres`:
```yaml
  redis:
    image: redis:7
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 3s
      retries: 10
```
`.env.example` — add: `RATE_LIMIT_STORAGE_URI=redis://localhost:6379/0`

`tests/conftest.py` — add an **autouse** fixture so every test starts with clean counters:
```python
@pytest.fixture(autouse=True)
def reset_rate_limits():
    from app import rate_limit
    rate_limit.reset()
    yield
```

**Tests** (`tests/test_rate_limit_core.py`, using the default `memory://` storage): calling
`enforce(parse("2/minute"), "k")` three times → first two pass, third raises `HTTPException` with
`status_code == 429` and a `Retry-After` header; two different identifier tuples don't share a
counter; after `reset()` the counter is clear again; with `rate_limit_enabled=False` (monkeypatch
the setting / clear the `get_settings` cache) `enforce` never raises.

### Task 2 — Login timing-oracle fix
**Files:** `app/services/auth_service.py`; test `tests/test_auth_service.py` (extend).

Give the absent-user / null-hash path the same argon2 work as the wrong-password path:
```python
# module level, computed once
_DUMMY_PASSWORD_HASH = hash_password("timing-equalization-placeholder")

def login(db: Session, *, email: str, password: str) -> tuple[User, str]:
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.password_hash is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)  # burn ~equal time; result ignored
        raise InvalidCredentialsError
    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError
    # ... unchanged session creation ...
```
Still one uniform `InvalidCredentialsError` for unknown-email, null-hash, and wrong-password (no
enumeration via exception type — preserved).

**Tests** (behavioral, not timing-based — timing assertions are flaky): use `mocker.spy` on
`app.services.auth_service.verify_password` and assert it **is called** on an unknown-email login
attempt (proving the constant-work path runs); assert the exception is still
`InvalidCredentialsError`; add the previously-missing test for the **null-`password_hash`** user
branch (create a user with `password_hash=None`, attempt login, assert `InvalidCredentialsError`
and that `verify_password` was still called). Existing login tests still pass.

### Task 3 — Apply limits to auth routes
**Files:** `app/api/v1/auth.py`; test `tests/test_rate_limit_auth.py`.

`login` — add `request: Request` to the signature and enforce **both** limits at the very top
(before any DB work), referencing the module-level items so tests can monkeypatch:
```python
from fastapi import Request
from app import rate_limit

@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit.enforce(rate_limit.LOGIN_IP, "login-ip", rate_limit.client_ip(request))
    rate_limit.enforce(rate_limit.LOGIN_EMAIL, "login-email", payload.email.lower())
    ...  # unchanged
```
`signup` — add a per-IP limit as a dependency (runs before the handler body):
```python
def _limit_signup_ip(request: Request) -> None:
    rate_limit.enforce(rate_limit.SIGNUP_IP, "signup-ip", rate_limit.client_ip(request))

@router.post("/signup", ..., dependencies=[Depends(_limit_signup_ip)])
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> User:
    ...  # unchanged
```

**Tests** (`tests/test_rate_limit_auth.py`, via the `client` fixture; the autouse
`reset_rate_limits` keeps tests isolated). To keep tests fast and decoupled from the exact prod
numbers, **monkeypatch the relevant limit item to a small window** for each test (e.g.
`monkeypatch.setattr(rate_limit, "LOGIN_EMAIL", parse("2/minute"))`), then:
- login per-email: 3 failed logins for the same email → 3rd returns 429 with `Retry-After`; a login
  for a *different* email is still allowed (proves per-email keying, not per-IP).
- login per-IP: monkeypatch `LOGIN_IP` small and `LOGIN_EMAIL` high; N+1 logins across *different*
  emails from the one TestClient IP → the (N+1)th is 429 (proves per-IP keying).
- signup per-IP: monkeypatch `SIGNUP_IP` small; N+1 signups (distinct emails, to avoid the 409
  duplicate path) → (N+1)th is 429.
- A single normal login/signup under the (real) limits still succeeds — confirm the existing
  `test_auth_api.py` suite still passes unchanged.

### Task 4 — Apply per-user limits to money endpoints
**Files:** `app/api/v1/packs.py`; test `tests/test_rate_limit_packs.py`.

Add per-user limit dependencies that reuse `get_current_user` (shared within the request), reading
the module-level items at call time:
```python
from fastapi import Request  # (Request not needed here; key is the user id)
from app import rate_limit

def _limit_purchase(current_user: User = Depends(get_current_user)) -> None:
    rate_limit.enforce(rate_limit.PURCHASE_USER, "purchase-user", str(current_user.id))

def _limit_open(current_user: User = Depends(get_current_user)) -> None:
    rate_limit.enforce(rate_limit.OPEN_USER, "open-user", str(current_user.id))

@router.post("/purchase", ..., dependencies=[Depends(_limit_purchase)])
def purchase_pack(...):  # unchanged body
@router.post("/{pack_id}/open", ..., dependencies=[Depends(_limit_open)])
def open_pack(...):      # unchanged body
```
(An unauthenticated request still gets 401 from `get_current_user`, not 429 — fine; per-user
limiting only applies to authenticated callers.)

**Tests** (`tests/test_rate_limit_packs.py`, via `client`, seeding funding through
`append_entry(admin_adjustment)` and a published odds table + eligible game exactly like
`test_packs_api.py`): monkeypatch `PURCHASE_USER` to a small window; sign up + log in, fund the
wallet enough for several purchases, then purchase until the limit trips and assert the crossing
request is 429 with `Retry-After` (and that the earlier successful purchases actually happened).
Confirm the existing `test_packs_api.py` suite still passes under the real (30/min) limits.

---

## Verification (whole-slice)

```bash
cd backend && docker compose up -d          # now also starts redis
uv run pytest -v                            # all prior + new rate-limit tests green (uses memory://, no redis needed)
# manual smoke test against real redis:
RATE_LIMIT_STORAGE_URI=redis://localhost:6379/0 uv run uvicorn app.main:app --reload
#   hammer POST /api/v1/auth/login with bad creds -> eventually 429 + Retry-After header
#   confirm the counter is shared: restart uvicorn mid-burst, limit still in effect (redis-backed)
#   unknown-email vs wrong-password login now take ~the same time (timing oracle closed)
```

Headline checks: an over-limit request returns **429 with a `Retry-After` header**; unknown-email
login now performs an argon2 verify (spy-verified) so it no longer short-circuits faster than a
real attempt; the full existing 87-test suite still passes with limiting active (thanks to the
autouse per-test reset and prod limits set well above any legitimate test flow).

## Out of Scope (later slices)

- Account lockout / exponential backoff after N failed logins; CAPTCHA.
- Global or read-endpoint rate limiting.
- Proper client-IP resolution behind a reverse proxy (X-Forwarded-For + trusted-proxy setting) —
  `client_ip` uses the direct socket address for MVP.
- Stripe deposits and any webhook rate/abuse handling.
- Distributed-limit niceties (moving-window strategy, sliding logs) — FixedWindow is used for MVP.

## Execution Note

After approval, copy to `docs/superpowers/plans/2026-07-16-rate-limiting.md` and execute with
**subagent-driven-development** (fresh implementer + task reviewer per task, whole-branch review at
the end), same as the prior two slices.
