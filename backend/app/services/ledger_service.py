import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LedgerEntry, User
from app.models.enums import LedgerEntryType


class InsufficientBalanceError(Exception):
    pass


def get_balance(db: Session, user_id: uuid.UUID) -> int:
    # wallet_balance_cached is maintained transactionally by append_entry under a
    # row lock on the user row, so it is authoritative for the current balance;
    # ledger_entries remains the immutable, append-only audit trail of how it got there.
    user = db.execute(select(User).where(User.id == user_id)).scalar_one()
    return int(user.wallet_balance_cached)


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
