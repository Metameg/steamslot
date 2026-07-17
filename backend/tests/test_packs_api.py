import uuid

from fastapi.testclient import TestClient as RealTestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.main import app as real_app
from app.models import Game, LedgerEntry, OddsBand, OddsTable, Pack, PackType, User
from app.models.enums import LedgerEntryType

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
BALANCE_URL = "/api/v1/wallet/balance"
PACK_TYPES_URL = "/api/v1/packs/types"
PURCHASE_URL = "/api/v1/packs/purchase"
PULLS_URL = "/api/v1/packs/pulls"


def _signup_payload(email="packbuyer@example.com", password="correct horse battery staple"):
    return {
        "email": email,
        "password": password,
        "display_name": "Pack Buyer",
        "age_attested": True,
        "accept_terms": True,
    }


def _signup_and_login(client, email="packbuyer@example.com", password="correct horse battery staple"):
    client.post(SIGNUP_URL, json=_signup_payload(email=email, password=password))
    response = client.post(LOGIN_URL, json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def _fund_user(db_session, user_id, amount, key):
    from app.services.ledger_service import append_entry

    append_entry(
        db_session,
        user_id=user_id,
        entry_type=LedgerEntryType.admin_adjustment,
        amount=amount,
        idempotency_key=key,
    )


def test_pack_types_is_public_and_lists_active_types(client, basic_odds_setup):
    response = client.get(PACK_TYPES_URL)

    assert response.status_code == 200
    body = response.json()
    assert any(pt["id"] == str(basic_odds_setup["pack_type"].id) for pt in body)


def test_full_authed_flow_signup_login_fund_purchase_open_balance_pulls(
    client, db_session, basic_odds_setup
):
    user_body = _signup_and_login(client, email="fullflow@example.com")
    user_id = uuid.UUID(user_body["id"])
    pack_type = basic_odds_setup["pack_type"]

    types_response = client.get(PACK_TYPES_URL)
    assert types_response.status_code == 200

    _fund_user(db_session, user_id, pack_type.price + 5000, key=f"fund-{user_id}")

    purchase_response = client.post(
        PURCHASE_URL,
        json={"pack_type_id": str(pack_type.id)},
        headers={"Idempotency-Key": "purchase-key-1"},
    )
    assert purchase_response.status_code == 201
    pack_body = purchase_response.json()
    assert pack_body["status"] == "unopened"
    assert pack_body["price_paid_cents"] == pack_type.price

    open_response = client.post(f"/api/v1/packs/{pack_body['id']}/open")
    assert open_response.status_code == 200
    pull_body = open_response.json()
    assert pull_body["locked_value_cents"] > 0
    assert pull_body["game_title"]

    balance_response = client.get(BALANCE_URL)
    assert balance_response.status_code == 200
    assert balance_response.json()["balance_cents"] == 5000

    pulls_response = client.get(PULLS_URL)
    assert pulls_response.status_code == 200
    pulls_body = pulls_response.json()
    assert len(pulls_body) == 1
    assert pulls_body[0]["id"] == pull_body["id"]


def test_unauthenticated_purchase_returns_401(client, basic_odds_setup):
    response = client.post(
        PURCHASE_URL,
        json={"pack_type_id": str(basic_odds_setup["pack_type"].id)},
        headers={"Idempotency-Key": "unauth-key"},
    )
    assert response.status_code == 401


def test_purchase_missing_idempotency_key_returns_422(client, basic_odds_setup):
    _signup_and_login(client, email="noidem@example.com")

    response = client.post(
        PURCHASE_URL,
        json={"pack_type_id": str(basic_odds_setup["pack_type"].id)},
    )
    assert response.status_code == 422


def test_insufficient_balance_purchase_returns_402_and_leaves_ledger_and_balance_untouched(
    client, db_session, basic_odds_setup
):
    """A purchase attempt that fails because the user's balance is too low must
    leave the wallet balance unchanged and must not create a LedgerEntry. Both facts
    are genuinely provable through the shared `client`/`db_session` fixture, because
    append_entry (ledger_service.py) raises InsufficientBalanceError BEFORE it ever
    calls db.add(entry) or mutates user.wallet_balance_cached -- so there is nothing
    to roll back for *these* two facts; they are true even without a rollback.

    The Pack row itself is a different story -- see
    test_insufficient_balance_purchase_leaves_no_orphaned_pack_end_to_end_via_real_get_db
    below, plus this file's docstring-length comment on that test, for why proving
    "no orphaned Pack row" requires bypassing this shared-session `client` fixture
    entirely, and why that is NOT a sign that Task 1's rollback fix is broken."""
    user_body = _signup_and_login(client, email="poor@example.com")
    user_id = uuid.UUID(user_body["id"])
    pack_type = basic_odds_setup["pack_type"]

    # Deliberately do NOT fund the user -- wallet balance stays at 0, which is less
    # than pack_type.price (1000 cents from basic_odds_setup).
    response = client.post(
        PURCHASE_URL,
        json={"pack_type_id": str(pack_type.id)},
        headers={"Idempotency-Key": "poor-purchase-key"},
    )

    assert response.status_code == 402

    user = db_session.get(User, user_id)
    assert user.wallet_balance_cached == 0

    ledger_entries = db_session.scalars(
        select(LedgerEntry).where(LedgerEntry.user_id == user_id)
    ).all()
    assert ledger_entries == [], "a LedgerEntry was created for a failed purchase"

    balance_response = client.get(BALANCE_URL)
    assert balance_response.json()["balance_cents"] == 0


def test_insufficient_balance_purchase_leaves_no_orphaned_pack_end_to_end_via_real_get_db(
    engine, session_factory, monkeypatch
):
    """THE single most important test in this slice.

    Why this test does NOT use the `client`/`db_session` fixtures from conftest.py:
    those fixtures deliberately share ONE SQLAlchemy Session, under ONE savepoint,
    across every request issued within a test (see the `client` fixture's own
    docstring: "no request ever perform[s] a real commit"). `app.db.get_db` is
    overridden out entirely -- `_override_get_db` just does `yield db_session`, with
    no try/except and therefore no call to `.rollback()` on failure. That is correct
    and intentional for that fixture's job (fast, isolated tests that can see each
    other's writes within one test) but it means a test built on it CANNOT observe
    whether the real get_db's rollback-on-exception actually ran -- and indeed, if
    you query for the Pack row through that SAME shared session after a failed
    purchase, you find it still there: `purchase_pack` did `db.add(pack); db.flush()`
    before calling `append_entry`, that flush sent a real INSERT into the ambient
    transaction, and nothing in `_override_get_db` ever undoes it. That is a property
    of the test fixture's design, not evidence that Task 1's fix doesn't work -- see
    this task's report for the full trace.

    So instead, this test reaches for the REAL, unmodified `app.db.get_db` -- the
    exact function Task 1 fixed -- and exercises it through a REAL, separate
    TestClient hitting the actual `/api/v1/packs/purchase` route, exactly the way
    `tests/test_db_transaction.py::test_get_db_rolls_back_on_exception` already
    proves get_db's rollback in isolation for a synthetic route. This test proves the
    same mechanism closes the specific gap this whole slice exists for: a purchase
    that fails on the ledger debit, after `purchase_pack` has already flushed an
    unpaid Pack row, leaves NO trace once the real per-request session is rolled back
    and closed. Verification happens through `session_factory()`, a genuinely
    independent connection, only after the HTTP request/response cycle has fully
    completed -- i.e. after get_db's own commit-or-rollback-then-close has already
    run for that request.
    """
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_local)

    email = "e2e-rollback-proof@example.com"
    password = "correct horse battery staple"

    seed = session_factory()
    try:
        pack_type = PackType(name="E2E Rollback Proof", price=100_000, description="")
        seed.add(pack_type)
        seed.flush()
        odds_table = OddsTable(pack_type_id=pack_type.id, version=1, is_published=True)
        seed.add(odds_table)
        seed.flush()
        band = OddsBand(
            odds_table_id=odds_table.id,
            name="Common",
            probability=1.0,
            min_price=100,
            max_price=200_000,
            sort_order=0,
        )
        seed.add(band)
        game = Game(
            steam_app_id=900555,
            title="E2E Rollback Game",
            regular_price=50_000,
            header_image_url=None,
        )
        seed.add(game)
        seed.commit()
        pack_type_id = pack_type.id
        odds_table_id = odds_table.id
        band_id = band.id
        game_id = game.id
    finally:
        seed.close()

    user_id: uuid.UUID | None = None
    try:
        with RealTestClient(real_app) as real_client:
            signup_response = real_client.post(SIGNUP_URL, json=_signup_payload(email=email, password=password))
            assert signup_response.status_code == 201
            user_id = uuid.UUID(signup_response.json()["id"])

            login_response = real_client.post(LOGIN_URL, json={"email": email, "password": password})
            assert login_response.status_code == 200

            # Deliberately do NOT fund this user -- wallet balance is 0, far below
            # pack_type.price (100_000 cents).
            purchase_response = real_client.post(
                PURCHASE_URL,
                json={"pack_type_id": str(pack_type_id)},
                headers={"Idempotency-Key": "e2e-rollback-key"},
            )
            assert purchase_response.status_code == 402

        verify = session_factory()
        try:
            packs = verify.scalars(select(Pack).where(Pack.user_id == user_id)).all()
            assert packs == [], "a Pack row survived a real, end-to-end failed purchase"

            user = verify.get(User, user_id)
            assert user.wallet_balance_cached == 0

            ledger_entries = verify.scalars(
                select(LedgerEntry).where(LedgerEntry.user_id == user_id)
            ).all()
            assert ledger_entries == [], "a LedgerEntry was created for a failed purchase"
        finally:
            verify.close()
    finally:
        cleanup = session_factory()
        try:
            if user_id is not None:
                cleanup.query(Pack).filter(Pack.user_id == user_id).delete()
                cleanup.query(LedgerEntry).filter(LedgerEntry.user_id == user_id).delete()
                from app.models import Session as SessionModel

                cleanup.query(SessionModel).filter(SessionModel.user_id == user_id).delete()
                cleanup.query(User).filter(User.id == user_id).delete()
            cleanup.query(OddsBand).filter(OddsBand.id == band_id).delete()
            cleanup.query(OddsTable).filter(OddsTable.id == odds_table_id).delete()
            cleanup.query(PackType).filter(PackType.id == pack_type_id).delete()
            cleanup.query(Game).filter(Game.id == game_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_idempotent_purchase_same_key_twice_returns_same_pack_debits_once(
    client, db_session, basic_odds_setup
):
    user_body = _signup_and_login(client, email="idempotent@example.com")
    user_id = uuid.UUID(user_body["id"])
    pack_type = basic_odds_setup["pack_type"]
    _fund_user(db_session, user_id, pack_type.price * 3, key=f"fund-{user_id}")

    first = client.post(
        PURCHASE_URL,
        json={"pack_type_id": str(pack_type.id)},
        headers={"Idempotency-Key": "same-key"},
    )
    second = client.post(
        PURCHASE_URL,
        json={"pack_type_id": str(pack_type.id)},
        headers={"Idempotency-Key": "same-key"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    balance_response = client.get(BALANCE_URL)
    assert balance_response.json()["balance_cents"] == pack_type.price * 3 - pack_type.price


def test_open_nonexistent_pack_returns_404(client, basic_odds_setup):
    _signup_and_login(client, email="opener404@example.com")

    response = client.post(f"/api/v1/packs/{uuid.uuid4()}/open")
    assert response.status_code == 404


def test_open_pack_not_owned_by_caller_returns_404(client, db_session, basic_odds_setup):
    owner_body = _signup_and_login(client, email="owner@example.com")
    owner_id = uuid.UUID(owner_body["id"])
    pack_type = basic_odds_setup["pack_type"]
    _fund_user(db_session, owner_id, pack_type.price, key=f"fund-{owner_id}")

    purchase_response = client.post(
        PURCHASE_URL,
        json={"pack_type_id": str(pack_type.id)},
        headers={"Idempotency-Key": "owner-key"},
    )
    assert purchase_response.status_code == 201
    pack_id = purchase_response.json()["id"]

    # log out owner, log in as intruder
    client.post("/api/v1/auth/logout")
    _signup_and_login(client, email="intruder@example.com")

    response = client.post(f"/api/v1/packs/{pack_id}/open")
    assert response.status_code == 404
