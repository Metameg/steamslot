import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LedgerEntry, User
from app.models.enums import LedgerEntryType


class InsufficientBalanceError(Exception):
    pass


def get_balance(db: Session, user_id: uuid.UUID) -> int:
    # ledger_entries is the source of truth for balances (append-only, auditable,
    # self-healing). wallet_balance_cached exists only as append_entry's own
    # row-locked mutation target, kept in lockstep with every ledger insert — it is
    # never read here, so get_balance always reflects the immutable ledger, not a
    # second, potentially-divergent cache.
    total = db.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.user_id == user_id)
    ).scalar_one()
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
