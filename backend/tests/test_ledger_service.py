import threading

import pytest

from app.models import LedgerEntry, User
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


def test_concurrent_credits_do_not_lose_updates(session_factory):
    # This test exercises real, independently-committed connections racing against
    # each other, so setup and cleanup must use session_factory (real commits) rather
    # than the db_session fixture (savepoint-scoped; never visible to other connections
    # until the outer transaction is rolled back at teardown).
    setup_session = session_factory()
    try:
        user = _make_user(setup_session, email="race@example.com")
        setup_session.commit()
        user_id = user.id
    finally:
        setup_session.close()

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

    verify_session = session_factory()
    try:
        assert get_balance(verify_session, user_id) == 2000
    finally:
        verify_session.close()
        cleanup_session = session_factory()
        try:
            cleanup_session.query(LedgerEntry).filter(LedgerEntry.user_id == user_id).delete()
            cleanup_session.query(User).filter(User.id == user_id).delete()
            cleanup_session.commit()
        finally:
            cleanup_session.close()
