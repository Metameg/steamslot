# Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the SteamSlot backend's foundational core — project scaffold, the full 11-table
schema via migrations, the append-only ledger service, real-Steam catalog seeding, and the
server-authoritative pack purchase/open (RNG) service — as working, independently-tested Python
code with no HTTP layer, auth, or Stripe integration yet.

**Architecture:** FastAPI (Python) backend, SQLAlchemy 2.0 ORM (sync `Session`), Alembic
migrations, Postgres via docker-compose for both dev and test databases. All business logic lives
in `app/services/` as plain functions taking a `Session` — this task's deliverable is that service
layer plus the schema underneath it, so it can be exercised directly from tests before any API
route exists.

**Tech Stack:** Python (whatever `python3` resolves to locally, currently 3.14; `requires-python
>=3.12`), `uv` for dependency/venv management, FastAPI, SQLAlchemy 2.0, Alembic, `psycopg[binary]`
v3, Pydantic v2 + `pydantic-settings`, `httpx`, `pytest`. Postgres 16 via Docker.

This plan resequences the design doc's stated build order (`scaffolding → schema/migrations →
auth → catalog+odds seed scripts → deposit → buy/open/RNG → ...`): it builds
**scaffolding → schema/migrations → ledger → catalog seeding → odds/RNG engine → pack
purchase/open** *before* auth and the HTTP/Stripe layer. Rationale: the design doc's own Testing
Priority section names the odds engine and the ledger as the two things that most need to be
correct first, and both are fully testable as service-layer functions against a real Postgres
without any auth or API surface. Auth, the FastAPI route layer, Stripe deposits, buyback,
redemption requests, and withdrawals are a separate follow-up plan.

## Global Constraints

- All money is stored as **integer minor units (cents)** with a currency code — never floats.
  (`design.md` → Tech Stack Detail, Money Model)
- `ledger_entries` is **append-only** and is the source of truth for balances;
  `users.wallet_balance_cached` is a derived, cached convenience value only.
  (`design.md` → Database Schema, Money Integrity Rules)
- A won game's value is its **regular/MSRP price** (`price_overview.initial` from Steam, **not**
  `final`/discounted), snapshotted onto the `pull` at win time and locked.
  (`design.md` → Key Decisions: Pricing basis)
- RNG is **server-authoritative**: the outcome is rolled and committed inside one DB transaction
  before any client ever sees it. No provably-fair scheme for MVP.
  (`design.md` → Server-Authoritative RNG & Reveal)
- Money-affecting operations use **row-level locking** (`SELECT ... FOR UPDATE`) and
  **idempotency keys**; balance can never go negative.
  (`design.md` → Money Integrity Rules)
- Odds tables are **versioned**; a `pack` locks to the `odds_table` version published at purchase
  time. If a band has no eligible game in stock, exclude that band from the roll and re-normalize
  over what remains — never promise a prize not in stock.
  (`design.md` → Database Schema: odds_tables/odds_bands, Pack/pull lifecycle)
- Single canonical region/currency for MVP: **US / USD**.
  (`design.md` → Catalog Seeding, Key Decisions)
- No admin UI, no auth, no Stripe integration, no HTTP endpoints in this plan — service-layer and
  schema only. (See "Resequencing" note above.)

## Local Setup (for every task in this plan)

Run once, before Task 1's steps:

```bash
cd /home/metameg/Work/steamslot
mkdir -p backend
cd backend
```

All file paths below are relative to `backend/` unless stated otherwise.

---

### Task 1: Backend Project Scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/docker-compose.yml`
- Create: `backend/docker/init-test-db.sql`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: a `uv`-managed project at `backend/`; a running Postgres via `docker compose up -d`
  with a `steamslot` (dev) and `steamslot_test` (test) database; a FastAPI `app` object in
  `app/main.py` importable as `from app.main import app`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Create the project scaffold files**

`backend/pyproject.toml`:

```toml
[project]
name = "steamslot-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0.36",
    "alembic>=1.14",
    "psycopg[binary]>=3.2",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "httpx>=0.27",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-mock>=3.14",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`backend/.env.example`:

```
DATABASE_URL=postgresql+psycopg://steamslot:steamslot@localhost:5432/steamslot
TEST_DATABASE_URL=postgresql+psycopg://steamslot:steamslot@localhost:5432/steamslot_test
```

`backend/docker/init-test-db.sql`:

```sql
CREATE DATABASE steamslot_test;
```

`backend/docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: steamslot
      POSTGRES_PASSWORD: steamslot
      POSTGRES_DB: steamslot
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/init-test-db.sql:/docker-entrypoint-initdb.d/init-test-db.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U steamslot"]
      interval: 2s
      timeout: 3s
      retries: 10

volumes:
  pgdata:
```

`backend/app/__init__.py`: empty file.

- [ ] **Step 3: Install dependencies and start Postgres**

```bash
cd backend
cp .env.example .env
uv sync
docker compose up -d
```

Wait for readiness, then verify:

```bash
docker compose exec -T postgres pg_isready -U steamslot
```

Expected: `/var/run/postgresql:5432 - accepting connections`. Also verify the test DB was created:

```bash
docker compose exec -T postgres psql -U steamslot -d steamslot_test -c "SELECT 1;"
```

Expected: a one-row `1` result (proves `steamslot_test` exists, per the init script).

- [ ] **Step 4: Run the test to verify it fails**

```bash
uv run pytest tests/test_health.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'` (or similar import error).

- [ ] **Step 5: Implement the health endpoint**

`backend/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="SteamSlot API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
uv run pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/metameg/Work/steamslot
git add backend/pyproject.toml backend/.env.example backend/docker-compose.yml \
  backend/docker/init-test-db.sql backend/app/__init__.py backend/app/main.py \
  backend/tests/test_health.py backend/.gitignore 2>/dev/null
git add backend/uv.lock 2>/dev/null
git commit -m "feat(backend): project scaffold with health endpoint"
```

(Note: `backend/.env` must NOT be committed — it holds local dev credentials. Add
`backend/.env` and `backend/.venv/` to a `backend/.gitignore`, or confirm the repo-root
`.gitignore` already covers `.env`/`.venv` patterns before staging — it does, per the existing
root `.gitignore`.)

---

### Task 2: Database Models and Initial Migration

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/app/db.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/base.py`
- Create: `backend/app/models/enums.py`
- Create: `backend/app/models/user.py`
- Create: `backend/app/models/ledger.py`
- Create: `backend/app/models/catalog.py`
- Create: `backend/app/models/packs.py`
- Create: `backend/app/models/fulfillment.py`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`,
  `backend/alembic/versions/0001_initial_schema.py` (generated then reviewed)
- Test: `backend/tests/test_schema.py`

**Interfaces:**
- Consumes: Postgres running via `docker compose` (Task 1).
- Produces: SQLAlchemy models `User`, `LedgerEntry`, `Game`, `PackType`, `OddsTable`, `OddsBand`,
  `Pack`, `Pull`, `RedemptionRequest`, `Withdrawal`, `StripeEvent` importable from `app.models`,
  with exact field names/types as written below (later tasks depend on these verbatim).
  `get_settings()` returning a `Settings` object with `.database_url` / `.test_database_url`.
  `SessionLocal` and `get_db()` in `app.db`. A migrated `steamslot_test` database.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_schema.py`:

```python
from sqlalchemy import create_engine, inspect

from app.config import get_settings

EXPECTED_TABLES = {
    "users", "ledger_entries", "games", "pack_types", "odds_tables",
    "odds_bands", "packs", "pulls", "redemption_requests", "withdrawals",
    "stripe_events",
}


def test_all_tables_exist():
    settings = get_settings()
    engine = create_engine(settings.test_database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - table_names
    assert not missing, f"missing tables: {missing}"
    engine.dispose()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_schema.py -v
```

Expected: FAIL — `app.config` doesn't exist yet (`ModuleNotFoundError`).

- [ ] **Step 3: Write config and db session setup**

`backend/app/config.py`:

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://steamslot:steamslot@localhost:5432/steamslot"
    test_database_url: str = (
        "postgresql+psycopg://steamslot:steamslot@localhost:5432/steamslot_test"
    )
    steam_api_base: str = "https://store.steampowered.com/api"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/app/db.py`:

```python
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()
engine = create_engine(_settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Write the models**

`backend/app/models/base.py`:

```python
from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
```

`backend/app/models/enums.py`:

```python
import enum


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class LedgerEntryType(str, enum.Enum):
    deposit = "deposit"
    pack_purchase = "pack_purchase"
    buyback_credit = "buyback_credit"
    withdrawal = "withdrawal"
    refund = "refund"
    admin_adjustment = "admin_adjustment"


class PackStatus(str, enum.Enum):
    unopened = "unopened"
    opened = "opened"


class PullStatus(str, enum.Enum):
    vaulted = "vaulted"
    bought_back = "bought_back"
    redeem_requested = "redeem_requested"
    redeemed = "redeemed"


class RedemptionStatus(str, enum.Enum):
    pending = "pending"
    fulfilled = "fulfilled"
    cancelled = "cancelled"


class WithdrawalStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"


class StripeEventStatus(str, enum.Enum):
    received = "received"
    processed = "processed"
    failed = "failed"
```

`backend/app/models/user.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow
from app.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, default=UserRole.user
    )
    age_attested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_connect_account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    wallet_balance_cached: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
```

`backend/app/models/ledger.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow
from app.models.enums import LedgerEntryType


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        SAEnum(LedgerEntryType, name="ledger_entry_type"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    reference_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
```

`backend/app/models/catalog.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Game(Base):
    __tablename__ = "games"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    steam_app_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    regular_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    region: Mapped[str] = mapped_column(String, nullable=False, default="US")
    header_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    price_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
```

`backend/app/models/packs.py`:

```python
import decimal
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow
from app.models.enums import PackStatus, PullStatus


class PackType(Base):
    __tablename__ = "pack_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class OddsTable(Base):
    __tablename__ = "odds_tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pack_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pack_types.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OddsBand(Base):
    __tablename__ = "odds_bands"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    odds_table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("odds_tables.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    probability: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    min_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Pack(Base):
    __tablename__ = "packs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    pack_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pack_types.id"), nullable=False
    )
    odds_table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("odds_tables.id"), nullable=False
    )
    price_paid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[PackStatus] = mapped_column(
        SAEnum(PackStatus, name="pack_status"), nullable=False, default=PackStatus.unopened
    )
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Pull(Base):
    __tablename__ = "pulls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id"), unique=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id"), nullable=False)
    odds_band_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("odds_bands.id"), nullable=False
    )
    locked_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[PullStatus] = mapped_column(
        SAEnum(PullStatus, name="pull_status"), nullable=False, default=PullStatus.vaulted
    )
    roll_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
```

`backend/app/models/fulfillment.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow
from app.models.enums import RedemptionStatus, StripeEventStatus, WithdrawalStatus


class RedemptionRequest(Base):
    __tablename__ = "redemption_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pull_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pulls.id"), unique=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[RedemptionStatus] = mapped_column(
        SAEnum(RedemptionStatus, name="redemption_status"), nullable=False, default=RedemptionStatus.pending
    )
    delivered_key: Mapped[str | None] = mapped_column(String, nullable=True)
    fulfilled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[WithdrawalStatus] = mapped_column(
        SAEnum(WithdrawalStatus, name="withdrawal_status"), nullable=False, default=WithdrawalStatus.pending
    )
    stripe_payout_id: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stripe_event_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[StripeEventStatus] = mapped_column(
        SAEnum(StripeEventStatus, name="stripe_event_status"), nullable=False, default=StripeEventStatus.received
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`backend/app/models/__init__.py`:

```python
from app.models.base import Base
from app.models.catalog import Game
from app.models.fulfillment import RedemptionRequest, StripeEvent, Withdrawal
from app.models.ledger import LedgerEntry
from app.models.packs import OddsBand, OddsTable, Pack, PackType, Pull
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "LedgerEntry",
    "Game",
    "PackType",
    "OddsTable",
    "OddsBand",
    "Pack",
    "Pull",
    "RedemptionRequest",
    "Withdrawal",
    "StripeEvent",
]
```

- [ ] **Step 5: Set up Alembic and write env.py**

```bash
uv run alembic init alembic
```

Replace the generated `backend/alembic/env.py` entirely with:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Note: `get_url()` reads `Settings().database_url`, which itself reads the `DATABASE_URL` env var
via `pydantic-settings`. To target the *test* database when generating/applying this migration,
set `DATABASE_URL` to the test URL for these specific commands (see Step 6) — do not edit
`alembic.ini`'s placeholder `sqlalchemy.url` line; it is unused (overridden by `env.py`).

- [ ] **Step 6: Generate and review the migration, then apply it to the test database**

```bash
DATABASE_URL=postgresql+psycopg://steamslot:steamslot@localhost:5432/steamslot_test \
  uv run alembic revision --autogenerate -m "initial schema"
```

Open the generated file at `backend/alembic/versions/<hash>_initial_schema.py` and verify it
contains `op.create_table(...)` calls for all 11 tables listed in `EXPECTED_TABLES` above, with
the enum types (`user_role`, `ledger_entry_type`, `pack_status`, `pull_status`,
`redemption_status`, `withdrawal_status`, `stripe_event_status`) and foreign keys matching the
models. Rename the file to `backend/alembic/versions/0001_initial_schema.py` for a stable,
readable name (update the file's own `revision = "..."` identifier only if the autogenerated
filename hash was embedded there — leave the `revision`/`down_revision` values as generated).

Apply it:

```bash
DATABASE_URL=postgresql+psycopg://steamslot:steamslot@localhost:5432/steamslot_test \
  uv run alembic upgrade head
```

Also apply it to the dev database (used by later manual scripts):

```bash
uv run alembic upgrade head
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
uv run pytest tests/test_schema.py -v
```

Expected: PASS — all 11 tables present in `steamslot_test`.

- [ ] **Step 8: Commit**

```bash
cd /home/metameg/Work/steamslot
git add backend/app/config.py backend/app/db.py backend/app/models/ \
  backend/alembic.ini backend/alembic/env.py backend/alembic/script.py.mako \
  backend/alembic/versions/ backend/tests/test_schema.py
git commit -m "feat(backend): add SQLAlchemy models and initial Alembic migration"
```

---

### Task 3: Ledger Service (append-only, idempotent, row-locked)

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/ledger_service.py`
- Test: `backend/tests/test_ledger_service.py`

**Interfaces:**
- Consumes: `User`, `LedgerEntry` models and `get_settings()` (Task 2).
- Produces: `get_balance(db, user_id) -> int`, `append_entry(db, *, user_id, entry_type, amount,
  idempotency_key, currency="USD", reference_type=None, reference_id=None) -> LedgerEntry`, and
  `InsufficientBalanceError`, all in `app.services.ledger_service`. Test fixtures `engine`,
  `db_session`, `session_factory` in `tests/conftest.py`, reused by all later test files.

**Invariant every later task must preserve:** `get_balance` always recomputes from
`ledger_entries` (the source of truth, per Global Constraints) — it never reads
`wallet_balance_cached` directly. `append_entry` separately uses `wallet_balance_cached` internally,
under the same `SELECT ... FOR UPDATE` row lock as the balance check, purely as the fast
locked-mutation target — the two stay consistent only because **every** balance-affecting write,
including test setup, goes through `append_entry`. Never set `wallet_balance_cached` directly
(not in application code, not in test fixtures, not in later tasks) — seed a starting balance with
a real `append_entry(..., entry_type=LedgerEntryType.admin_adjustment, ...)` call instead, exactly
as `_make_user` below does.

- [ ] **Step 1: Write the test fixtures**

`backend/tests/conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings


@pytest.fixture(scope="session")
def engine():
    settings = get_settings()
    eng = create_engine(settings.test_database_url)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    connection = engine.connect()
    trans = connection.begin()
    session_maker = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    session = session_maker()
    yield session
    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
```

This fixture set assumes `steamslot_test` is already migrated (Task 2, Step 6). `db_session`
wraps each test in a real transaction with a savepoint so code under test may call
`session.commit()` internally without ending the outer transaction — the whole test's effects are
rolled back on teardown. `session_factory` hands out sessions bound directly to the shared engine,
each with its own connection — required for genuine concurrency tests where multiple threads must
hold independent DB connections/locks simultaneously.

- [ ] **Step 2: Write the failing tests**

`backend/app/services/__init__.py`: empty file.

`backend/tests/test_ledger_service.py`:

```python
import threading

import pytest

from app.models import User
from app.models.enums import LedgerEntryType
from app.services.ledger_service import InsufficientBalanceError, append_entry, get_balance


def _make_user(db_session, email="ledger@example.com", balance=0) -> User:
    user = User(email=email, display_name="Ledger Test", wallet_balance_cached=0)
    db_session.add(user)
    db_session.flush()
    if balance:
        append_entry(
            db_session,
            user_id=user.id,
            entry_type=LedgerEntryType.admin_adjustment,
            amount=balance,
            idempotency_key=f"seed-{user.id}",
        )
    return user


def test_get_balance_is_zero_for_new_user(db_session):
    user = _make_user(db_session)
    assert get_balance(db_session, user.id) == 0


def test_append_entry_credits_increase_balance(db_session):
    user = _make_user(db_session)
    append_entry(
        db_session,
        user_id=user.id,
        entry_type=LedgerEntryType.deposit,
        amount=5000,
        idempotency_key="credit-1",
    )
    assert get_balance(db_session, user.id) == 5000
    assert user.wallet_balance_cached == 5000


def test_append_entry_debits_decrease_balance(db_session):
    user = _make_user(db_session, balance=1000)
    append_entry(
        db_session,
        user_id=user.id,
        entry_type=LedgerEntryType.pack_purchase,
        amount=-400,
        idempotency_key="debit-1",
    )
    assert get_balance(db_session, user.id) == 600


def test_append_entry_raises_when_balance_would_go_negative(db_session):
    user = _make_user(db_session, balance=100)
    with pytest.raises(InsufficientBalanceError):
        append_entry(
            db_session,
            user_id=user.id,
            entry_type=LedgerEntryType.pack_purchase,
            amount=-200,
            idempotency_key="debit-2",
        )
    assert get_balance(db_session, user.id) == 100


def test_append_entry_is_idempotent_on_replayed_key(db_session):
    user = _make_user(db_session)
    first = append_entry(
        db_session,
        user_id=user.id,
        entry_type=LedgerEntryType.deposit,
        amount=300,
        idempotency_key="replay-1",
    )
    second = append_entry(
        db_session,
        user_id=user.id,
        entry_type=LedgerEntryType.deposit,
        amount=300,
        idempotency_key="replay-1",
    )
    assert first.id == second.id
    assert get_balance(db_session, user.id) == 300  # not 600 - not double-applied


def test_concurrent_credits_do_not_lose_updates(db_session, session_factory):
    user = _make_user(db_session, email="race@example.com")
    db_session.commit()
    user_id = user.id

    errors: list[Exception] = []

    def credit(i: int) -> None:
        session = session_factory()
        try:
            append_entry(
                session,
                user_id=user_id,
                entry_type=LedgerEntryType.deposit,
                amount=100,
                idempotency_key=f"race-{i}",
            )
            session.commit()
        except Exception as exc:  # pragma: no cover - captured for assertion below
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=credit, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []

    verify_session = session_factory()()
    try:
        assert get_balance(verify_session, user_id) == 2000
    finally:
        verify_session.close()
        db_session.query(User).filter(User.id == user_id).delete()
        db_session.commit()
```

Note `session_factory` is a `sessionmaker`; calling it (`session_factory()`) yields a session. The
final cleanup deletes the test user directly since this test bypasses the `db_session` fixture's
auto-rollback for its concurrent writes (each thread commits for real, since row-locking must be
exercised against real, separately-committed transactions).

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_ledger_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ledger_service'`.

- [ ] **Step 4: Implement the ledger service**

`backend/app/services/ledger_service.py`:

```python
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LedgerEntry, User
from app.models.enums import LedgerEntryType


class InsufficientBalanceError(Exception):
    pass


def get_balance(db: Session, user_id: uuid.UUID) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.user_id == user_id)
    )
    return int(total)


def append_entry(
    db: Session,
    *,
    user_id: uuid.UUID,
    entry_type: LedgerEntryType,
    amount: int,
    idempotency_key: str,
    currency: str = "USD",
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
) -> LedgerEntry:
    existing = db.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key))
    if existing is not None:
        return existing

    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()

    new_balance = user.wallet_balance_cached + amount
    if new_balance < 0:
        raise InsufficientBalanceError(
            f"balance {user.wallet_balance_cached} cannot cover amount {amount}"
        )

    entry = LedgerEntry(
        user_id=user_id,
        entry_type=entry_type,
        amount=amount,
        currency=currency,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
    )
    db.add(entry)
    user.wallet_balance_cached = new_balance
    db.flush()
    return entry
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_ledger_service.py -v
```

Expected: PASS, all 6 tests (including the concurrency test — it must show all 20 threads
succeeded and the final balance is exactly 2000, proving the `SELECT ... FOR UPDATE` row lock
serialized the concurrent balance updates with no lost writes).

- [ ] **Step 6: Commit**

```bash
cd /home/metameg/Work/steamslot
git add backend/tests/conftest.py backend/app/services/__init__.py \
  backend/app/services/ledger_service.py backend/tests/test_ledger_service.py
git commit -m "feat(backend): add append-only ledger service with row-locked balance updates"
```

---

### Task 4: Steam Catalog Client

**Files:**
- Create: `backend/app/catalog/__init__.py`
- Create: `backend/app/catalog/steam_client.py`
- Test: `backend/tests/test_steam_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure function, no DB).
- Produces: `fetch_game(appid: int, *, cc: str = "us", client: httpx.Client | None = None) ->
  FetchedGame` and `SteamFetchError` in `app.catalog.steam_client`. `FetchedGame` has fields
  `steam_app_id: int`, `title: str`, `regular_price: int`, `currency: str`,
  `header_image_url: str | None`. Task 5's `refresh_catalog_fixture.py` script depends on this
  exact signature and field set.

- [ ] **Step 1: Write the failing tests**

`backend/app/catalog/__init__.py`: empty file.

`backend/tests/test_steam_client.py`:

```python
import httpx
import pytest

from app.catalog.steam_client import SteamFetchError, fetch_game


def _client_with_response(json_payload: dict, status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_game_parses_regular_price_not_discounted():
    payload = {
        "440": {
            "success": True,
            "data": {
                "name": "Team Fortress 2",
                "is_free": False,
                "price_overview": {"initial": 999, "final": 499, "currency": "USD"},
                "header_image": "https://example.com/tf2.jpg",
            },
        }
    }
    client = _client_with_response(payload)
    game = fetch_game(440, client=client)
    assert game.steam_app_id == 440
    assert game.title == "Team Fortress 2"
    assert game.regular_price == 999  # initial, NOT final/discounted
    assert game.currency == "USD"
    assert game.header_image_url == "https://example.com/tf2.jpg"


def test_fetch_game_raises_on_unsuccessful_lookup():
    client = _client_with_response({"999999": {"success": False}})
    with pytest.raises(SteamFetchError):
        fetch_game(999999, client=client)


def test_fetch_game_raises_on_free_game():
    payload = {"480": {"success": True, "data": {"name": "Spacewar", "is_free": True}}}
    client = _client_with_response(payload)
    with pytest.raises(SteamFetchError):
        fetch_game(480, client=client)


def test_fetch_game_raises_when_no_price_overview():
    payload = {"111": {"success": True, "data": {"name": "Unreleased Game", "is_free": False}}}
    client = _client_with_response(payload)
    with pytest.raises(SteamFetchError):
        fetch_game(111, client=client)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_steam_client.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.catalog.steam_client'`.

- [ ] **Step 3: Implement the client**

`backend/app/catalog/steam_client.py`:

```python
from dataclasses import dataclass

import httpx


@dataclass
class FetchedGame:
    steam_app_id: int
    title: str
    regular_price: int
    currency: str
    header_image_url: str | None


class SteamFetchError(Exception):
    pass


def fetch_game(appid: int, *, cc: str = "us", client: httpx.Client | None = None) -> FetchedGame:
    owns_client = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        response = client.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "cc": cc, "l": "en"},
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            client.close()

    entry = payload.get(str(appid))
    if entry is None or not entry.get("success"):
        raise SteamFetchError(f"appdetails lookup failed for appid={appid}")

    data = entry["data"]
    if data.get("is_free"):
        raise SteamFetchError(f"appid={appid} is free; no MSRP to catalog")

    price_overview = data.get("price_overview")
    if not price_overview:
        raise SteamFetchError(f"appid={appid} has no price_overview (unreleased/region-locked)")

    return FetchedGame(
        steam_app_id=appid,
        title=data["name"],
        regular_price=price_overview["initial"],
        currency=price_overview["currency"],
        header_image_url=data.get("header_image"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_steam_client.py -v
```

Expected: PASS, all 4 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/metameg/Work/steamslot
git add backend/app/catalog/__init__.py backend/app/catalog/steam_client.py \
  backend/tests/test_steam_client.py
git commit -m "feat(backend): add Steam appdetails client reading regular (non-sale) price"
```

---

### Task 5: Catalog Fixture Generation and Seeding

**Files:**
- Create: `backend/scripts/__init__.py`
- Create: `backend/scripts/refresh_catalog_fixture.py`
- Create: `backend/scripts/seed_catalog.py`
- Create: `backend/data/catalog_seed.json` (generated by running the script for real — see Step 4)
- Test: `backend/tests/test_refresh_catalog_fixture.py`
- Test: `backend/tests/test_seed_catalog.py`

**Interfaces:**
- Consumes: `fetch_game`/`SteamFetchError` (Task 4), `Game` model + `SessionLocal` (Task 2).
- Produces: a committed fixture file `data/catalog_seed.json`; `seed_catalog(db, fixture_path=
  FIXTURE_PATH) -> int` in `app` scripts, used directly by later tasks' test setup for a realistic
  catalog if needed.

- [ ] **Step 1: Write the curated app ID list and fixture-refresh script**

`backend/scripts/__init__.py`: empty file.

`backend/scripts/refresh_catalog_fixture.py`:

```python
"""Developer tool: refreshes data/catalog_seed.json from live Steam prices.

Run occasionally, never at seed/app-start time:
    uv run python scripts/refresh_catalog_fixture.py
"""

import json
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from app.catalog.steam_client import SteamFetchError, fetch_game

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog_seed.json"

# Curated app IDs spanning MVP price bands. See docs/design.md "Catalog Seeding".
# NOTE: verify each fetched title/price against the intended game when this script is run for
# real (Step 4) - a wrong app ID will either fail the fetch (skipped) or resolve to the wrong
# game, both visible in the printed output.
CURATED_APP_IDS = [
    # ~$1-5
    1794680,  # Vampire Survivors
    945360,  # Among Us
    # ~$5-15
    620,  # Portal 2
    105600,  # Terraria
    2379780,  # Balatro
    413150,  # Stardew Valley
    367520,  # Hollow Knight
    # ~$15-30
    1145360,  # Hades
    504230,  # Celeste
    268910,  # Cuphead
    321040,  # Inscryption
    646570,  # Slay the Spire
    588650,  # Dead Cells
    753640,  # Outer Wilds
    # ~$30-50
    292030,  # The Witcher 3
    632470,  # Disco Elysium
    427520,  # Factorio
    294100,  # RimWorld
    553420,  # Tunic
    # ~$50-70
    1245620,  # Elden Ring
    1091500,  # Cyberpunk 2077
    1086940,  # Baldur's Gate 3
    1174180,  # Red Dead Redemption 2
    814380,  # Sekiro
]


def main() -> None:
    client = httpx.Client(timeout=10.0)
    fixture: list[dict] = []
    for appid in CURATED_APP_IDS:
        try:
            game = fetch_game(appid, client=client)
        except SteamFetchError as exc:
            print(f"skipping appid={appid}: {exc}")
            continue
        fixture.append(asdict(game))
        print(f"fetched {game.title} (${game.regular_price / 100:.2f})")
        time.sleep(0.5)  # politeness delay
    client.close()

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(fixture)} games to {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
```

`backend/tests/test_refresh_catalog_fixture.py`:

```python
from scripts.refresh_catalog_fixture import CURATED_APP_IDS


def test_curated_app_ids_are_unique():
    assert len(CURATED_APP_IDS) == len(set(CURATED_APP_IDS))


def test_curated_app_ids_span_expected_count():
    assert len(CURATED_APP_IDS) >= 20
```

- [ ] **Step 2: Run test to verify it passes (sanity-only, no network)**

```bash
uv run pytest tests/test_refresh_catalog_fixture.py -v
```

Expected: PASS immediately (this test only checks the static list, not live data).

- [ ] **Step 3: Write the seed script and its failing tests**

`backend/scripts/seed_catalog.py`:

```python
"""Idempotent catalog seeder: upserts games from the committed fixture.

Run after migrations, no network access:
    uv run python scripts/seed_catalog.py
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Game

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog_seed.json"


def seed_catalog(db: Session, fixture_path: Path = FIXTURE_PATH) -> int:
    entries = json.loads(fixture_path.read_text())
    count = 0
    for entry in entries:
        game = db.scalar(select(Game).where(Game.steam_app_id == entry["steam_app_id"]))
        if game is None:
            game = Game(steam_app_id=entry["steam_app_id"])
            db.add(game)
        game.title = entry["title"]
        game.regular_price = entry["regular_price"]
        game.currency = entry["currency"]
        game.header_image_url = entry["header_image_url"]
        game.region = "US"
        game.is_eligible = True
        count += 1
    db.commit()
    return count


if __name__ == "__main__":
    with SessionLocal() as session:
        n = seed_catalog(session)
        print(f"seeded/updated {n} games")
```

`backend/tests/test_seed_catalog.py`:

```python
import json
from pathlib import Path

from sqlalchemy import select

from app.models import Game
from scripts.seed_catalog import seed_catalog

FIXTURE = [
    {
        "steam_app_id": 620,
        "title": "Portal 2",
        "regular_price": 999,
        "currency": "USD",
        "header_image_url": "https://example.com/portal2.jpg",
    },
    {
        "steam_app_id": 1245620,
        "title": "Elden Ring",
        "regular_price": 5999,
        "currency": "USD",
        "header_image_url": "https://example.com/eldenring.jpg",
    },
]


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "catalog_seed.json"
    path.write_text(json.dumps(FIXTURE))
    return path


def test_seed_catalog_inserts_games(db_session, tmp_path):
    fixture_path = _write_fixture(tmp_path)
    count = seed_catalog(db_session, fixture_path=fixture_path)
    assert count == 2
    titles = set(db_session.scalars(select(Game.title)))
    assert titles == {"Portal 2", "Elden Ring"}


def test_seed_catalog_is_idempotent(db_session, tmp_path):
    fixture_path = _write_fixture(tmp_path)
    seed_catalog(db_session, fixture_path=fixture_path)
    seed_catalog(db_session, fixture_path=fixture_path)
    games = db_session.scalars(select(Game)).all()
    assert len(games) == 2


def test_seed_catalog_updates_existing_price(db_session, tmp_path):
    fixture_path = _write_fixture(tmp_path)
    seed_catalog(db_session, fixture_path=fixture_path)
    updated = json.loads(fixture_path.read_text())
    updated[0]["regular_price"] = 799
    fixture_path.write_text(json.dumps(updated))
    seed_catalog(db_session, fixture_path=fixture_path)
    game = db_session.scalar(select(Game).where(Game.steam_app_id == 620))
    assert game.regular_price == 799
```

Run to verify these fail:

```bash
uv run pytest tests/test_seed_catalog.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.seed_catalog'`.

- [ ] **Step 4: Generate the real fixture, then run tests to verify they pass**

Run the live fetch for real (one-time, network-dependent — this is the *only* place a live Steam
call happens in this task):

```bash
uv run python scripts/refresh_catalog_fixture.py
```

Inspect the printed output line by line: confirm each title matches the app ID's intended game
(per the comments in `CURATED_APP_IDS`) and that prices span all five bands (~$1–5 through
~$50–70). If any app ID resolved to an unexpected title or was skipped, fix the ID in
`CURATED_APP_IDS` and re-run. Once `data/catalog_seed.json` looks correct:

```bash
uv run pytest tests/test_seed_catalog.py -v
```

Expected: PASS, all 3 tests (these run against the synthetic `FIXTURE` constant in the test file,
not the real fixture — they verify `seed_catalog`'s upsert logic, independent of what real data
ended up in `data/catalog_seed.json`).

Then seed the dev database with the real fixture and spot-check it:

```bash
uv run python scripts/seed_catalog.py
docker compose exec -T postgres psql -U steamslot -d steamslot -c \
  "SELECT title, regular_price FROM games ORDER BY regular_price;"
```

Expected: one row per curated game, prices in ascending order spanning roughly $1–$70.

- [ ] **Step 5: Commit**

```bash
cd /home/metameg/Work/steamslot
git add backend/scripts/__init__.py backend/scripts/refresh_catalog_fixture.py \
  backend/scripts/seed_catalog.py backend/data/catalog_seed.json \
  backend/tests/test_refresh_catalog_fixture.py backend/tests/test_seed_catalog.py
git commit -m "feat(backend): add catalog fixture refresh + idempotent seed script with real games"
```

---

### Task 6: Odds/RNG Engine

**Files:**
- Modify: `backend/tests/conftest.py` (add shared odds/game test fixtures)
- Create: `backend/app/services/rng_engine.py`
- Test: `backend/tests/test_rng_engine.py`

**Interfaces:**
- Consumes: `Game`, `OddsBand`, `OddsTable`, `PackType` models (Task 2).
- Produces: `roll(db, bands: list[OddsBand]) -> RollResult`, `expected_value(db, bands:
  list[OddsBand]) -> float`, `eligible_games_for_band(db, band) -> list[Game]`,
  `NoEligibleGamesError`, all in `app.services.rng_engine`. `RollResult` has fields `band:
  OddsBand`, `game: Game`, `effective_probabilities: dict[str, float]` (keyed by
  `str(band.id)`). Adds fixtures `_make_band`, `_make_game`, `basic_odds_setup` to
  `tests/conftest.py` — Task 7 reuses `basic_odds_setup` directly.

- [ ] **Step 1: Add shared fixtures to conftest**

Append to `backend/tests/conftest.py`:

```python
from app.models import Game, OddsBand, OddsTable, PackType


def _make_band(db, odds_table_id, name, probability, min_price, max_price, sort_order=0):
    band = OddsBand(
        odds_table_id=odds_table_id,
        name=name,
        probability=probability,
        min_price=min_price,
        max_price=max_price,
        sort_order=sort_order,
    )
    db.add(band)
    db.flush()
    return band


def _make_game(db, appid, title, price):
    game = Game(steam_app_id=appid, title=title, regular_price=price, header_image_url=None)
    db.add(game)
    db.flush()
    return game


@pytest.fixture()
def basic_odds_setup(db_session):
    pack_type = PackType(name="Basic", price=1000, description="")
    db_session.add(pack_type)
    db_session.flush()
    odds_table = OddsTable(pack_type_id=pack_type.id, version=1, is_published=True)
    db_session.add(odds_table)
    db_session.flush()

    common = _make_band(db_session, odds_table.id, "Common", 0.70, 100, 500)
    rare = _make_band(db_session, odds_table.id, "Rare", 0.25, 501, 1500)
    grail = _make_band(db_session, odds_table.id, "Grail", 0.05, 1501, 6000)

    _make_game(db_session, 900001, "Cheap Game", 300)
    _make_game(db_session, 900002, "Mid Game", 900)
    _make_game(db_session, 900003, "Grail Game", 5000)

    return {"pack_type": pack_type, "odds_table": odds_table, "bands": [common, rare, grail]}
```

Note: the `appid` values used here (`900001`–`900003`) are deliberately outside any real Steam
app ID range used in `CURATED_APP_IDS`, to avoid colliding with the seeded catalog if both are
ever present in the same database.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_rng_engine.py`:

```python
from collections import Counter

import pytest

from app.models import Game
from app.services.rng_engine import NoEligibleGamesError, expected_value, roll


def test_roll_distribution_matches_published_odds(db_session, basic_odds_setup):
    bands = basic_odds_setup["bands"]
    counts = Counter()
    n = 4000
    for _ in range(n):
        result = roll(db_session, bands)
        counts[result.band.name] += 1

    assert abs(counts["Common"] / n - 0.70) < 0.03
    assert abs(counts["Rare"] / n - 0.25) < 0.03
    assert abs(counts["Grail"] / n - 0.05) < 0.02


def test_roll_picks_game_within_band_price_range(db_session, basic_odds_setup):
    bands = basic_odds_setup["bands"]
    for _ in range(200):
        result = roll(db_session, bands)
        assert result.band.min_price <= result.game.regular_price <= result.band.max_price


def test_roll_excludes_empty_band_and_renormalizes(db_session, basic_odds_setup):
    bands = basic_odds_setup["bands"]
    grail_game = db_session.query(Game).filter_by(title="Grail Game").one()
    grail_game.is_eligible = False
    db_session.flush()

    for _ in range(100):
        result = roll(db_session, bands)
        assert result.band.name != "Grail"


def test_roll_raises_when_no_games_eligible(db_session, basic_odds_setup):
    for game in db_session.query(Game).all():
        game.is_eligible = False
    db_session.flush()

    with pytest.raises(NoEligibleGamesError):
        roll(db_session, basic_odds_setup["bands"])


def test_expected_value_below_pack_price(db_session, basic_odds_setup):
    pack_type = basic_odds_setup["pack_type"]
    bands = basic_odds_setup["bands"]
    ev = expected_value(db_session, bands)
    # 0.70*300 + 0.25*900 + 0.05*5000 = 210 + 225 + 250 = 685
    assert ev == pytest.approx(685, abs=1)
    assert ev < pack_type.price


def test_expected_value_renormalizes_when_a_band_has_no_eligible_games(db_session, basic_odds_setup):
    # Mirrors test_roll_excludes_empty_band_and_renormalizes: expected_value() must exclude an
    # empty band and re-weight the remainder exactly as roll() does, not silently understate EV
    # by leaving the empty band's probability mass out of total_weight entirely.
    bands = basic_odds_setup["bands"]
    common_game = db_session.query(Game).filter_by(title="Cheap Game").one()
    common_game.is_eligible = False
    db_session.flush()

    ev = expected_value(db_session, bands)
    # Common (0.70) excluded; Rare (0.25, avg 900) and Grail (0.05, avg 5000) re-normalize over
    # total_weight=0.30: (0.25/0.30)*900 + (0.05/0.30)*5000 = 750 + 833.33... = 1583.33...
    assert ev == pytest.approx(1583.33, abs=1)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_rng_engine.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.rng_engine'`.

- [ ] **Step 4: Implement the RNG engine**

`backend/app/services/rng_engine.py`:

```python
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Game, OddsBand


class NoEligibleGamesError(Exception):
    pass


@dataclass
class RollResult:
    band: OddsBand
    game: Game
    effective_probabilities: dict[str, float]


def eligible_games_for_band(db: Session, band: OddsBand) -> list[Game]:
    return list(
        db.scalars(
            select(Game).where(
                Game.is_eligible.is_(True),
                Game.regular_price >= band.min_price,
                Game.regular_price <= band.max_price,
            )
        )
    )


def roll(db: Session, bands: list[OddsBand]) -> RollResult:
    rng = secrets.SystemRandom()

    candidates: list[tuple[OddsBand, list[Game]]] = []
    for band in bands:
        games = eligible_games_for_band(db, band)
        if games:
            candidates.append((band, games))

    if not candidates:
        raise NoEligibleGamesError("no odds band has an eligible game in stock")

    total_weight = sum(float(band.probability) for band, _ in candidates)
    effective_probabilities = {
        str(band.id): float(band.probability) / total_weight for band, _ in candidates
    }

    roll_point = rng.random() * total_weight
    cumulative = 0.0
    chosen_band, chosen_games = candidates[-1]
    for band, games in candidates:
        cumulative += float(band.probability)
        if roll_point <= cumulative:
            chosen_band, chosen_games = band, games
            break

    chosen_game = rng.choice(chosen_games)
    return RollResult(band=chosen_band, game=chosen_game, effective_probabilities=effective_probabilities)


def expected_value(db: Session, bands: list[OddsBand]) -> float:
    """Average payout per pack given roll()'s actual behavior: bands with no eligible
    games are excluded and the remaining bands' weights re-normalized, exactly as roll() does.
    total_weight MUST be computed only over bands that have an eligible game -- computing it over
    all input bands (then skipping empty ones in the loop without adjusting the weight) silently
    understates EV whenever any band is out of stock, defeating the one function whose job is to
    prove the house edge holds."""
    candidates: list[tuple[OddsBand, list[Game]]] = []
    for band in bands:
        games = eligible_games_for_band(db, band)
        if games:
            candidates.append((band, games))

    total_weight = sum(float(band.probability) for band, _ in candidates)
    if total_weight == 0:
        return 0.0
    ev = 0.0
    for band, games in candidates:
        avg_band_value = sum(g.regular_price for g in games) / len(games)
        ev += (float(band.probability) / total_weight) * avg_band_value
    return ev
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_rng_engine.py -v
```

Expected: PASS, all 5 tests. The distribution test is statistical — if it flakes on tolerance
(unlikely at n=4000 with these margins), re-run once; a repeated failure indicates a real bug in
the weighting logic, not sampling noise.

- [ ] **Step 6: Commit**

```bash
cd /home/metameg/Work/steamslot
git add backend/tests/conftest.py backend/app/services/rng_engine.py backend/tests/test_rng_engine.py
git commit -m "feat(backend): add server-authoritative odds engine with band re-normalization"
```

---

### Task 7: Pack Purchase and Open Service

**Files:**
- Create: `backend/app/services/pack_service.py`
- Test: `backend/tests/test_pack_service.py`

**Interfaces:**
- Consumes: `append_entry` (Task 3), `roll` (Task 6), `Pack`/`Pull`/`PackType`/`OddsTable`/
  `OddsBand`/`LedgerEntry` models (Task 2), `basic_odds_setup` fixture (Task 6).
- Produces: `purchase_pack(db, *, user_id, pack_type_id, idempotency_key) -> Pack`,
  `open_pack(db, *, user_id, pack_id) -> Pull`, `PackTypeUnavailableError`,
  `PackNotFoundError`, all in `app.services.pack_service`. This is the last task in this plan —
  the follow-up plan's HTTP layer calls these two functions directly.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_pack_service.py`:

```python
import threading

import pytest
from sqlalchemy import select

from app.models import Game, LedgerEntry, OddsBand, OddsTable, Pack, PackType, Pull, User
from app.models.enums import LedgerEntryType
from app.services.ledger_service import append_entry, get_balance
from app.services.pack_service import (
    PackNotFoundError,
    PackTypeUnavailableError,
    open_pack,
    purchase_pack,
)


def _make_user(db_session, email="packs@example.com", balance=10_000) -> User:
    user = User(email=email, display_name="Pack Test", wallet_balance_cached=0)
    db_session.add(user)
    db_session.flush()
    if balance:
        append_entry(
            db_session,
            user_id=user.id,
            entry_type=LedgerEntryType.admin_adjustment,
            amount=balance,
            idempotency_key=f"seed-{user.id}",
        )
    return user


def test_purchase_pack_debits_wallet_and_creates_unopened_pack(db_session, basic_odds_setup):
    user = _make_user(db_session)
    pack_type = basic_odds_setup["pack_type"]

    pack = purchase_pack(
        db_session, user_id=user.id, pack_type_id=pack_type.id, idempotency_key="buy-1"
    )

    assert pack.status.value == "unopened"
    assert pack.price_paid == pack_type.price
    assert pack.odds_table_id == basic_odds_setup["odds_table"].id
    assert get_balance(db_session, user.id) == 10_000 - pack_type.price


def test_purchase_pack_is_idempotent_on_replay(db_session, basic_odds_setup):
    user = _make_user(db_session)
    pack_type = basic_odds_setup["pack_type"]

    first = purchase_pack(
        db_session, user_id=user.id, pack_type_id=pack_type.id, idempotency_key="buy-2"
    )
    second = purchase_pack(
        db_session, user_id=user.id, pack_type_id=pack_type.id, idempotency_key="buy-2"
    )

    assert first.id == second.id
    assert get_balance(db_session, user.id) == 10_000 - pack_type.price  # debited once


def test_purchase_pack_raises_when_pack_type_inactive(db_session, basic_odds_setup):
    user = _make_user(db_session)
    pack_type = basic_odds_setup["pack_type"]
    pack_type.is_active = False
    db_session.flush()

    with pytest.raises(PackTypeUnavailableError):
        purchase_pack(db_session, user_id=user.id, pack_type_id=pack_type.id, idempotency_key="buy-3")


def test_purchase_pack_raises_when_no_published_odds_table(db_session, basic_odds_setup):
    user = _make_user(db_session)
    odds_table = basic_odds_setup["odds_table"]
    odds_table.is_published = False
    db_session.flush()

    with pytest.raises(PackTypeUnavailableError):
        purchase_pack(
            db_session,
            user_id=user.id,
            pack_type_id=basic_odds_setup["pack_type"].id,
            idempotency_key="buy-4",
        )


def test_open_pack_creates_pull_and_marks_opened(db_session, basic_odds_setup):
    user = _make_user(db_session)
    pack = purchase_pack(
        db_session,
        user_id=user.id,
        pack_type_id=basic_odds_setup["pack_type"].id,
        idempotency_key="buy-5",
    )

    pull = open_pack(db_session, user_id=user.id, pack_id=pack.id)

    assert pull.pack_id == pack.id
    assert pull.locked_value > 0
    db_session.refresh(pack)
    assert pack.status.value == "opened"
    assert pack.opened_at is not None


def test_open_pack_is_idempotent_on_repeat_call(db_session, basic_odds_setup):
    user = _make_user(db_session)
    pack = purchase_pack(
        db_session,
        user_id=user.id,
        pack_type_id=basic_odds_setup["pack_type"].id,
        idempotency_key="buy-6",
    )

    first = open_pack(db_session, user_id=user.id, pack_id=pack.id)
    second = open_pack(db_session, user_id=user.id, pack_id=pack.id)

    assert first.id == second.id
    pulls = db_session.scalars(select(Pull).where(Pull.pack_id == pack.id)).all()
    assert len(pulls) == 1


def test_open_pack_raises_for_wrong_user(db_session, basic_odds_setup):
    owner = _make_user(db_session, email="owner@example.com")
    intruder = _make_user(db_session, email="intruder@example.com")
    pack = purchase_pack(
        db_session,
        user_id=owner.id,
        pack_type_id=basic_odds_setup["pack_type"].id,
        idempotency_key="buy-7",
    )

    with pytest.raises(PackNotFoundError):
        open_pack(db_session, user_id=intruder.id, pack_id=pack.id)


def test_open_pack_raises_for_nonexistent_pack(db_session, basic_odds_setup):
    user = _make_user(db_session)
    import uuid

    with pytest.raises(PackNotFoundError):
        open_pack(db_session, user_id=user.id, pack_id=uuid.uuid4())


def test_concurrent_open_pack_only_rolls_once(session_factory):
    # This test deliberately does NOT use the `basic_odds_setup`/`db_session` fixtures: those
    # build rows inside a savepoint-scoped transaction that is never really committed, so a
    # session from `session_factory()` (a genuinely separate connection, exactly what the
    # concurrent threads below use) can never see them. Every row this test depends on must be
    # created and committed for real, via `session_factory()`, from the start.
    setup_session = session_factory()
    try:
        pack_type = PackType(name="ConcurrentTest", price=1000, description="")
        setup_session.add(pack_type)
        setup_session.flush()

        odds_table = OddsTable(pack_type_id=pack_type.id, version=1, is_published=True)
        setup_session.add(odds_table)
        setup_session.flush()

        band = OddsBand(
            odds_table_id=odds_table.id,
            name="Common",
            probability=1.0,
            min_price=100,
            max_price=10_000,
            sort_order=0,
        )
        setup_session.add(band)

        game = Game(steam_app_id=900099, title="Concurrency Test Game", regular_price=500, header_image_url=None)
        setup_session.add(game)
        setup_session.flush()

        user = User(email="opener@example.com", display_name="Pack Test", wallet_balance_cached=0)
        setup_session.add(user)
        setup_session.flush()
        append_entry(
            setup_session,
            user_id=user.id,
            entry_type=LedgerEntryType.admin_adjustment,
            amount=10_000,
            idempotency_key=f"seed-{user.id}",
        )

        pack = purchase_pack(
            setup_session, user_id=user.id, pack_type_id=pack_type.id, idempotency_key="buy-8"
        )
        setup_session.commit()

        user_id = user.id
        pack_id = pack.id
        pack_type_id = pack_type.id
        odds_table_id = odds_table.id
        band_id = band.id
        game_id = game.id
    finally:
        setup_session.close()

    errors: list[Exception] = []
    results: list = []

    def try_open() -> None:
        session = session_factory()
        try:
            pull = open_pack(session, user_id=user_id, pack_id=pack_id)
            session.commit()
            results.append(pull.id)
        except Exception as exc:  # pragma: no cover - captured for assertion below
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=try_open) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(set(results)) == 1  # every thread observed the SAME pull

    cleanup_session = session_factory()
    try:
        pulls = cleanup_session.scalars(select(Pull).where(Pull.pack_id == pack_id)).all()
        assert len(pulls) == 1

        cleanup_session.query(Pull).filter(Pull.pack_id == pack_id).delete()
        cleanup_session.query(Pack).filter(Pack.id == pack_id).delete()
        cleanup_session.query(LedgerEntry).filter(LedgerEntry.user_id == user_id).delete()
        cleanup_session.query(User).filter(User.id == user_id).delete()
        cleanup_session.query(OddsBand).filter(OddsBand.id == band_id).delete()
        cleanup_session.query(OddsTable).filter(OddsTable.id == odds_table_id).delete()
        cleanup_session.query(PackType).filter(PackType.id == pack_type_id).delete()
        cleanup_session.query(Game).filter(Game.id == game_id).delete()
        cleanup_session.commit()
    finally:
        cleanup_session.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_pack_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.pack_service'`.

- [ ] **Step 3: Implement the pack service**

`backend/app/services/pack_service.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LedgerEntry, OddsBand, OddsTable, Pack, PackType, Pull
from app.models.base import utcnow
from app.models.enums import LedgerEntryType, PackStatus, PullStatus
from app.services.ledger_service import append_entry
from app.services.rng_engine import roll


class PackTypeUnavailableError(Exception):
    pass


class PackNotFoundError(Exception):
    pass


def purchase_pack(
    db: Session, *, user_id: uuid.UUID, pack_type_id: uuid.UUID, idempotency_key: str
) -> Pack:
    pack_type = db.get(PackType, pack_type_id)
    if pack_type is None or not pack_type.is_active:
        raise PackTypeUnavailableError(f"pack_type {pack_type_id} is not available")

    odds_table = db.scalar(
        select(OddsTable)
        .where(OddsTable.pack_type_id == pack_type_id, OddsTable.is_published.is_(True))
        .order_by(OddsTable.version.desc())
    )
    if odds_table is None:
        raise PackTypeUnavailableError(f"pack_type {pack_type_id} has no published odds table")

    existing_entry = db.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key))
    if existing_entry is not None:
        pack = db.get(Pack, existing_entry.reference_id)
        assert pack is not None, "purchase ledger entry exists without a linked pack"
        return pack

    pack = Pack(
        user_id=user_id,
        pack_type_id=pack_type_id,
        odds_table_id=odds_table.id,
        price_paid=pack_type.price,
        status=PackStatus.unopened,
    )
    db.add(pack)
    db.flush()  # assign pack.id

    append_entry(
        db,
        user_id=user_id,
        entry_type=LedgerEntryType.pack_purchase,
        amount=-pack_type.price,
        idempotency_key=idempotency_key,
        reference_type="pack",
        reference_id=pack.id,
    )
    return pack


def open_pack(db: Session, *, user_id: uuid.UUID, pack_id: uuid.UUID) -> Pull:
    pack = db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if pack is None:
        raise PackNotFoundError(f"pack {pack_id} not found for user {user_id}")

    if pack.status == PackStatus.opened:
        existing_pull = db.scalar(select(Pull).where(Pull.pack_id == pack_id))
        assert existing_pull is not None, "opened pack has no linked pull"
        return existing_pull

    bands = list(db.scalars(select(OddsBand).where(OddsBand.odds_table_id == pack.odds_table_id)))
    result = roll(db, bands)

    pull = Pull(
        pack_id=pack.id,
        user_id=user_id,
        game_id=result.game.id,
        odds_band_id=result.band.id,
        locked_value=result.game.regular_price,
        status=PullStatus.vaulted,
        roll_metadata={"effective_probabilities": result.effective_probabilities},
    )
    db.add(pull)
    pack.status = PackStatus.opened
    pack.opened_at = utcnow()
    db.flush()
    return pull
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_pack_service.py -v
```

Expected: PASS, all 9 tests — including the concurrency test, which must show all 10 threads
observing the exact same `pull.id` and exactly one `Pull` row in the database, proving the row
lock on `Pack` prevented a double-roll.

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest -v
```

Expected: PASS, all tests across all seven tasks (health, schema, ledger, steam client, catalog
seeding, rng engine, pack service).

- [ ] **Step 6: Commit**

```bash
cd /home/metameg/Work/steamslot
git add backend/app/services/pack_service.py backend/tests/test_pack_service.py
git commit -m "feat(backend): add pack purchase/open service with idempotent server-authoritative rolls"
```

---

## Out of Scope for This Plan (next plan picks these up)

- Auth (signup/login, session/JWT), the FastAPI route layer wrapping these services, and
  request/response Pydantic schemas.
- Stripe: deposits (Payments), withdrawals (Connect/payouts), webhook handling (`stripe_events`).
- Buyback (`buyback_credit` ledger entries + `pull.status = bought_back`) and redemption request
  creation (`redemption_requests` rows) — the service functions exist for purchase/open only;
  buyback/redeem endpoints and their services are new work.
- The price-sync job (recurring `fetch_game` refresh against already-seeded `games`).
- Frontend (React/Vite) and the reveal animation.
- No admin UI (per the approved design doc).
- **Request-scoped transaction/rollback policy.** `purchase_pack` and `open_pack` both mutate
  multiple rows (e.g. `purchase_pack` flushes a `Pack` before calling `append_entry`, which can
  raise `InsufficientBalanceError`). They rely on the *caller* rolling back the whole session on
  any raised exception, which this plan's tests do implicitly (the `db_session` fixture rolls back
  after every test regardless of outcome). The next plan's FastAPI layer must establish this
  explicitly — e.g. a `get_db` dependency that rolls back on any unhandled exception during the
  request — or a partial write (an unopened `Pack` with no matching ledger debit) can persist.

## Verification (whole-plan)

After all 7 tasks:

```bash
cd /home/metameg/Work/steamslot/backend
docker compose up -d
uv run pytest -v
```

Expected: every test across `tests/test_health.py`, `tests/test_schema.py`,
`tests/test_ledger_service.py`, `tests/test_steam_client.py`,
`tests/test_refresh_catalog_fixture.py`, `tests/test_seed_catalog.py`,
`tests/test_rng_engine.py`, and `tests/test_pack_service.py` passes, with the two concurrency
tests (ledger, pack open) demonstrating no lost updates / no double-rolls under real parallel DB
transactions. `docker compose exec -T postgres psql -U steamslot -d steamslot -c "SELECT title,
regular_price FROM games ORDER BY regular_price;"` shows the real seeded catalog spanning roughly
$1–$70.
