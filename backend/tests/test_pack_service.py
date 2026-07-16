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
