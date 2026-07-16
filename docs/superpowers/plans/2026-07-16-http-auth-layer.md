# HTTP + Auth Layer — Implementation Plan (Slice 2)

## Context

The backend **foundation slice** is built, reviewed, and merged: the 11-table schema, the
append-only ledger service, the Steam catalog + seeding, the RNG/odds engine, and the pack
purchase/open service — all as a pure service layer with **no HTTP surface and no auth**. Two
things block turning it into a usable API:

1. `get_db` (`backend/app/db.py:13-18`) only *closes* the session — it never commits or rolls
   back. The foundation review flagged (Important) that `purchase_pack` flushes a `Pack` before
   the wallet debit can raise `InsufficientBalanceError`, so without request-scoped rollback a
   failed purchase can leave an unpaid `Pack` row. **This must be fixed before any route calls a
   write service.**
2. There is no way for a user to authenticate or to reach any service over HTTP.

This slice delivers an **authenticated REST API** over the existing services: request-scoped
transactions, email+password auth with revocable server-side sessions, and endpoints for the
already-built loop (list pack types → purchase → open → read balance/vault). It also folds in the
foundation review's second Important finding (missing FK indexes + a `wallet_balance_cached >= 0`
CHECK constraint). **No Stripe / money-in, no buyback / redeem / withdrawal, no frontend** — those
are later slices.

## Locked Decisions

- **Auth**: email + password, hashed with **argon2** (`argon2-cffi`). `users.password_hash`
  already exists (nullable, leaves room for OAuth later).
- **Sessions**: **server-side, revocable**. A high-entropy opaque token lives in an HTTP-only
  cookie; only its **sha256 hash** is stored, in a new `sessions` table. Logout / ban / compromise
  can revoke instantly.
- **Scope**: HTTP foundation + auth + wire existing services. Test/demo wallet funding uses the
  existing `append_entry(..., admin_adjustment, ...)` path (no deposits yet).
- **API** versioned under **`/api/v1`**.

## Global Constraints (carried from the foundation slice — still binding)

- Money is integer cents everywhere; `ledger_entries` is the source of truth; **never write
  `wallet_balance_cached` directly** (application code or tests) — seed balances via
  `append_entry(..., entry_type=LedgerEntryType.admin_adjustment, ...)`.
- **Service functions flush only; they never commit.** The request-scoped `get_db` owns
  commit-on-success / rollback-on-exception. This is the transaction boundary.
- **Never store raw secrets**: passwords are argon2 hashes; session tokens are stored as sha256
  hashes, never plaintext.
- Domain (service-layer) exceptions are mapped to HTTP status codes centrally, not re-invented per
  route.

## Existing Interfaces To Reuse (exact signatures — do not reimplement)

- `app.services.ledger_service`: `get_balance(db, user_id) -> int`;
  `append_entry(db, *, user_id, entry_type, amount, idempotency_key, currency="USD",
  reference_type=None, reference_id=None) -> LedgerEntry`; `InsufficientBalanceError`.
- `app.services.pack_service`: `purchase_pack(db, *, user_id, pack_type_id, idempotency_key) ->
  Pack`; `open_pack(db, *, user_id, pack_id) -> Pull`; `PackTypeUnavailableError`;
  `PackNotFoundError`.
- `app.services.rng_engine`: `NoEligibleGamesError`.
- `app.models`: `User` (`id, email, password_hash, display_name, role, age_attested,
  terms_accepted_at, wallet_balance_cached, ...`), `PackType` (`id, name, price, description,
  is_active`), `Pull` (`id, game_id, locked_value, status, created_at`), `Game` (`id, title,
  header_image_url, regular_price`), `LedgerEntryType` enum (`app.models.enums`).
- `app.models.base.utcnow()` for timezone-aware timestamps.
- `app.db`: `SessionLocal`, `engine`, `get_db` (to be reworked in Task 1).

## New File Structure

```
backend/app/
  security/__init__.py
  security/password.py        # argon2 hash/verify
  security/tokens.py          # session token generate + sha256 hash
  models/session.py           # Session model (+ export from models/__init__)
  services/auth_service.py    # signup / login / logout / authenticate + exceptions
  api/__init__.py
  api/deps.py                 # get_current_user dependency (+ re-export get_db)
  api/errors.py               # register_exception_handlers(app)
  api/v1/__init__.py          # aggregates the v1 routers under one APIRouter
  api/v1/auth.py              # /auth routes
  api/v1/wallet.py            # /wallet routes
  api/v1/packs.py             # /packs routes
  schemas/__init__.py
  schemas/auth.py             # SignupRequest, LoginRequest, UserResponse
  schemas/wallet.py           # BalanceResponse
  schemas/packs.py            # PackTypeResponse, PackResponse, PullResponse
  alembic/versions/0002_sessions.py
  alembic/versions/0003_indexes_and_wallet_check.py
```

Modify: `app/db.py` (get_db), `app/main.py` (routers, handlers, CORS), `app/config.py`
(cookie/session/CORS settings), `pyproject.toml` (add `argon2-cffi>=23` and `email-validator>=2`
— the latter is required by Pydantic's `EmailStr`).

## Request Lifecycle (the core design)

- **`get_db`** yields a session, **commits on success, rolls back on any exception, always
  closes**. Every request is one atomic transaction. Because FastAPI caches a dependency within a
  request, `get_current_user` and the route handler share the *same* session/transaction.
- Route handlers call service functions and let **domain exceptions propagate**; `api/errors.py`
  registers FastAPI exception handlers mapping each to a status code. `get_db`'s `except` rolls the
  transaction back before the handler formats the response.
- **Auth**: `get_current_user` reads the session cookie → `auth_service.authenticate(db, token)`
  → raises `HTTPException(401)` if `None`.
- **Session cookie**: HTTP-only, `SameSite=Lax`, `Secure` configurable (off in dev), name + TTL
  from settings.

## Endpoint Surface (v1)

| Method | Path | Auth | Input | Calls | Success |
|---|---|---|---|---|---|
| POST | `/api/v1/auth/signup` | no | SignupRequest (email, password, display_name, age_attested, accept_terms) | `auth_service.signup` | 201 UserResponse |
| POST | `/api/v1/auth/login` | no | LoginRequest (email, password) | `auth_service.login` → set cookie | 200 UserResponse |
| POST | `/api/v1/auth/logout` | cookie | — | `auth_service.logout` → clear cookie | 204 |
| GET | `/api/v1/auth/me` | yes | — | current user | 200 UserResponse |
| GET | `/api/v1/wallet/balance` | yes | — | `get_balance` | 200 BalanceResponse |
| GET | `/api/v1/packs/types` | no | — | `PackType` where is_active | 200 [PackTypeResponse] |
| POST | `/api/v1/packs/purchase` | yes | body: {pack_type_id}; header: `Idempotency-Key` | `purchase_pack` | 201 PackResponse |
| POST | `/api/v1/packs/{pack_id}/open` | yes | — | `open_pack` | 200 PullResponse |
| GET | `/api/v1/packs/pulls` | yes | — | `Pull` where user | 200 [PullResponse] |

`/packs/types` is intentionally public (browse before signup); everything money- or user-specific
requires auth.

## Exception → HTTP Mapping (registered in `api/errors.py`)

| Exception (source) | Status |
|---|---|
| `EmailAlreadyExistsError` (auth) | 409 |
| `InvalidCredentialsError` (auth) | 401 |
| `AgeNotAttestedError` / `TermsNotAcceptedError` (auth) | 422 |
| `InsufficientBalanceError` (ledger) | 402 |
| `PackTypeUnavailableError` (pack) | 409 |
| `PackNotFoundError` (pack) | 404 |
| `NoEligibleGamesError` (rng) | 409 |
| `sqlalchemy.exc.IntegrityError` (idempotency-key unique violation on a concurrent same-key purchase) | 409 |

The `IntegrityError → 409` mapping is the pragmatic close for the foundation review's noted
`purchase_pack` concurrency edge: on a genuine concurrent double-submit with the same key, one
request commits, the other's `append_entry` flush hits the unique constraint and 409s; the client
retries and hits `purchase_pack`'s normal idempotent-replay path (existing ledger entry → returns
the same pack). Combined with the Task 1 rollback fix, no unpaid `Pack` can persist. A coarse
global `IntegrityError → 409` is acceptable for this slice; a per-route narrowing can come later.

---

## Task Breakdown (each TDD, independently reviewable)

### Task 1 — Request-scoped transaction management (`get_db`)
**Files:** modify `app/db.py`; test `tests/test_db_transaction.py`.
Rework `get_db` to commit on success, rollback on exception, always close:
```python
def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```
**Tests** (mount a throwaway route on a local `FastAPI()` using `get_db` that writes a row then
optionally raises): success path commits the row; exception path leaves **no** row (rollback);
session is closed either way. This is the fix that closes the foundation review's partial-write
gap — the pack-purchase rollback is then verified end-to-end in Task 7.

### Task 2 — DB hardening migration (FK indexes + wallet CHECK)
**Files:** create `alembic/versions/0002_indexes_and_wallet_check.py`; test
`tests/test_db_constraints.py`.
Hand-written Alembic migration (autogenerate will not add FK indexes): `op.create_index` on
`ledger_entries.user_id`, `packs.user_id`, `pulls.user_id`, `odds_bands.odds_table_id`,
`odds_tables.pack_type_id`, `redemption_requests.user_id`, `redemption_requests.fulfilled_by`,
`withdrawals.user_id`; and `op.create_check_constraint("ck_users_wallet_nonneg", "users",
"wallet_balance_cached >= 0")`. (Unique columns — `idempotency_key`, `email`, `steam_app_id`,
`pack_id`, `pull_id`, `stripe_event_id` — are already indexed by their unique constraints; do not
double-index.) **Tests**: inspect the DB and assert the named indexes exist; assert a direct
`UPDATE users SET wallet_balance_cached = -1` raises an `IntegrityError`. Closes foundation review
Important finding #1. (Ordered as `0002` because it has no code dependency; sessions migration is
`0003`.)

### Task 3 — Password hashing + session tokens
**Files:** `app/security/__init__.py`, `app/security/password.py`, `app/security/tokens.py`;
add `argon2-cffi>=23` to `pyproject.toml`; test `tests/test_security.py`.
```python
# password.py
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
_ph = PasswordHasher()
def hash_password(pw: str) -> str: return _ph.hash(pw)
def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False
# tokens.py
import hashlib, secrets
def generate_session_token() -> str: return secrets.token_urlsafe(32)
def hash_token(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()
```
**Tests**: hash differs from plaintext and from a second hash of the same password (random salt);
`verify_password` true for right pw, false for wrong; `hash_token` is stable + 64-hex;
`generate_session_token` returns distinct high-entropy strings.

### Task 4 — Session model + migration
**Files:** `app/models/session.py`, export `Session` from `app/models/__init__.py`; create
`alembic/versions/0003_sessions.py` (autogenerate, review, rename); test extends
`tests/test_schema.py` (add `"sessions"` to expected tables).
```python
class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
```
Generate the migration with `DATABASE_URL` pointed at the test DB (same pattern as the foundation
migration), review it (one `create_table` for `sessions`, FK to `users`, unique on `token_hash`),
rename to `0003_sessions.py`, apply to both DBs.

### Task 5 — Auth service
**Files:** `app/services/auth_service.py`; test `tests/test_auth_service.py`.
Exceptions: `EmailAlreadyExistsError`, `InvalidCredentialsError`, `AgeNotAttestedError`,
`TermsNotAcceptedError`. `SESSION_TTL` from settings (`timedelta(days=settings.session_ttl_days)`).
```python
def signup(db, *, email, password, display_name, age_attested, accept_terms) -> User:
    if not age_attested: raise AgeNotAttestedError
    if not accept_terms: raise TermsNotAcceptedError
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise EmailAlreadyExistsError
    user = User(email=email, password_hash=hash_password(password), display_name=display_name,
                age_attested=True, terms_accepted_at=utcnow())
    db.add(user); db.flush(); return user

def login(db, *, email, password) -> tuple[User, str]:
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.password_hash is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError
    token = generate_session_token()
    db.add(Session(user_id=user.id, token_hash=hash_token(token),
                   expires_at=utcnow() + SESSION_TTL))
    db.flush(); return user, token

def authenticate(db, *, token: str | None) -> User | None:
    if not token: return None
    sess = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if sess is None or sess.revoked_at is not None or sess.expires_at <= utcnow():
        return None
    return db.get(User, sess.user_id)

def logout(db, *, token: str | None) -> None:
    if not token: return
    sess = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if sess is not None and sess.revoked_at is None:
        sess.revoked_at = utcnow()
```
**Tests** (use existing `db_session` fixture): signup happy path (user persisted, password hashed
not plaintext, `terms_accepted_at` set); signup raises on missing age/terms and on duplicate email;
login returns a working token + creates a session; login raises `InvalidCredentialsError` on wrong
password and unknown email; `authenticate` returns the user for a valid token, `None` for
unknown/expired/revoked; `logout` revokes so `authenticate` then returns `None`.

### Task 6 — Auth API (schemas, deps, error handlers, routes, app wiring, config)
**Files:** `app/schemas/auth.py`, `app/api/deps.py`, `app/api/errors.py`, `app/api/v1/auth.py`,
`app/api/v1/__init__.py`, `app/api/__init__.py`, `app/schemas/__init__.py`; modify `app/main.py`,
`app/config.py`; test `tests/test_auth_api.py`.
- **config additions**: `session_cookie_name="steamslot_session"`, `cookie_secure=False`,
  `session_ttl_days=30`, `cors_allow_origins=["http://localhost:5173"]`.
- **schemas**: `SignupRequest(email: EmailStr, password: str (min_length), display_name: str,
  age_attested: bool, accept_terms: bool)`, `LoginRequest(email, password)`,
  `UserResponse(id, email, display_name, role)` — never expose `password_hash`.
- **deps.py**: `get_current_user(session_token: str | None = Cookie(alias=<cookie name>), db =
  Depends(get_db))` → `authenticate` → `HTTPException(401)` if `None`; re-export `get_db`.
- **errors.py**: `register_exception_handlers(app)` covering the full mapping table above (auth
  exceptions here; ledger/pack/rng/IntegrityError added/confirmed in Task 7 or here — register all
  in one place).
- **routes**: signup (201), login (set HTTP-only cookie, 200), logout (revoke + delete cookie,
  204), me (200). Login/logout use FastAPI `Response.set_cookie` /`delete_cookie` with
  `httponly=True, samesite="lax", secure=settings.cookie_secure, max_age=SESSION_TTL seconds,
  path="/"`.
- **main.py**: add `CORSMiddleware(allow_origins=settings.cors_allow_origins,
  allow_credentials=True, allow_methods=["*"], allow_headers=["*"])`, call
  `register_exception_handlers(app)`, `app.include_router(v1_router, prefix="/api/v1")`, keep
  `/health`.
**Test harness (also used by Task 7) — read carefully.** FastAPI `TestClient` requests each run
through `get_db`, whose production form now *commits*. To keep tests isolated and to let a test
both seed rows and have the app see them, override the dependency:
`app.dependency_overrides[get_db] = lambda: (yield <the savepoint-scoped session>)`, yielding the
**same** `db_session`-style session (the conftest fixture built with
`join_transaction_mode="create_savepoint"`) for the whole test, and **not** committing/closing it
in the override (the fixture owns teardown, which rolls the outer transaction back). Because every
request in a test shares that one session/connection, writes from one request are visible to the
next without a real commit, and nothing persists past the test. Seed data (users via
`auth_service`/`append_entry`, odds tables, games) through that same session. Do **not** point the
app at an un-overridden `get_db` for these tests — real per-request commits would leak state
across tests. Add a shared `client` fixture in `tests/conftest.py` that wires this override.

**Tests** (via that `client` fixture): signup→201; duplicate email→409; signup missing
age/terms→422; login sets cookie + returns user; `me` with cookie→200, without cookie→401; wrong
password→401; logout→204 then `me`→401 (session revoked).

### Task 7 — Wallet + Packs API (capstone, wires the existing services)
**Files:** `app/schemas/wallet.py`, `app/schemas/packs.py`, `app/api/v1/wallet.py`,
`app/api/v1/packs.py` (register both in `api/v1/__init__.py`); test `tests/test_packs_api.py`.
- **schemas**: `BalanceResponse(balance_cents: int, currency: str)`;
  `PackTypeResponse(id, name, price_cents, description)`;
  `PackResponse(id, pack_type_id, status, price_paid_cents, purchased_at)`;
  `PullResponse(id, game_title, game_header_image_url, locked_value_cents, status, created_at)`
  (route loads the `Game` via `pull.game_id` to fill title/image).
- **routes**: `GET /wallet/balance` → `get_balance`; `GET /packs/types` (public) → active
  `PackType`s ordered by price; `POST /packs/purchase` (body `{pack_type_id}`, required
  `Idempotency-Key` header) → namespace key as `f"{user.id}:{key}"` then `purchase_pack` → 201;
  `POST /packs/{pack_id}/open` → `open_pack` → 200; `GET /packs/pulls` → user's `Pull`s newest
  first.
- Confirm the full exception mapping (InsufficientBalance→402, PackTypeUnavailable→409,
  PackNotFound→404, NoEligibleGames→409, IntegrityError→409) is registered.
**Tests** (`TestClient`, seeding a published odds table + eligible game + wallet funding via
`append_entry(admin_adjustment)`; reuse the fixture shapes from `test_pack_service.py`):
full authed flow signup→login→`/packs/types`→fund→purchase(with Idempotency-Key)→open→
`/wallet/balance` reflects the debit→`/packs/pulls` shows the win; unauthenticated purchase→401;
missing `Idempotency-Key`→422; **insufficient-balance purchase→402 AND assert no `Pack` row was
created for that user and balance unchanged** (the end-to-end proof that Task 1's rollback closes
the partial-write gap); idempotent purchase (same key twice → same pack id, wallet debited once);
open a non-owned / nonexistent pack → 404.

---

## Verification (whole-slice)

```bash
cd backend && docker compose up -d
uv run alembic upgrade head          # applies 0002 (indexes+check) and 0003 (sessions)
uv run pytest -v                     # all foundation + new auth/api tests green
# manual smoke test:
uv run uvicorn app.main:app --reload
#   POST /api/v1/auth/signup  -> 201
#   POST /api/v1/auth/login   -> 200 + Set-Cookie
#   GET  /api/v1/auth/me      -> 200 (with cookie)
#   GET  /api/v1/packs/types  -> 200
#   (fund the test user via a one-off admin_adjustment), POST /api/v1/packs/purchase (Idempotency-Key) -> 201
#   POST /api/v1/packs/{id}/open -> 200, GET /api/v1/wallet/balance reflects debit
```
The two headline correctness checks: the **insufficient-balance-purchase-leaves-no-pack** test
(Task 7) proves request-scoped rollback, and the **negative wallet CHECK** test (Task 2) proves the
DB-level balance floor.

## Out of Scope (later slices)

- Stripe deposits / Payments / webhooks / `stripe_events` processing (money-in).
- Buyback (`buyback_credit` + `pull.status = bought_back`), redemption requests, withdrawals.
- The recurring price-sync job.
- Frontend (React/Vite) + reveal animation.
- OAuth, password reset / email verification, rate limiting, admin UI.
- Adding `sessions` to the ER-diagram artifact (nice-to-have, not required).

## Execution Note

After approval, this plan will be copied to
`docs/superpowers/plans/2026-07-16-http-auth-layer.md` and executed with
**subagent-driven-development** (fresh implementer + task reviewer per task, whole-branch review at
the end), same as the foundation slice. Task 1 (the `get_db` rollback fix) goes first, before any
route wiring, per the foundation review's directive.
