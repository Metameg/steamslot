import uuid

from limits import parse
from sqlalchemy import select

from app import rate_limit
from app.models import Pack, User
from app.models.enums import LedgerEntryType

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
PURCHASE_URL = "/api/v1/packs/purchase"


def _signup_payload(email="ratepacker@example.com", password="correct horse battery staple"):
    return {
        "email": email,
        "password": password,
        "display_name": "Rate Packer",
        "age_attested": True,
        "accept_terms": True,
    }


def _signup_and_login(client, email="ratepacker@example.com", password="correct horse battery staple"):
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


def test_purchase_per_user_limit_trips_and_earlier_purchases_genuinely_happened(
    client, db_session, basic_odds_setup, monkeypatch
):
    monkeypatch.setattr(rate_limit, "PURCHASE_USER", parse("3/minute"))

    email = "purchase-limited@example.com"
    user_body = _signup_and_login(client, email=email)
    user_id = uuid.UUID(user_body["id"])
    pack_type = basic_odds_setup["pack_type"]

    # Fund generously -- enough for well more than the limit's worth of purchases.
    _fund_user(db_session, user_id, pack_type.price * 10, key=f"fund-{user_id}")

    responses = []
    for i in range(4):
        response = client.post(
            PURCHASE_URL,
            json={"pack_type_id": str(pack_type.id)},
            headers={"Idempotency-Key": f"purchase-limit-key-{i}"},
        )
        responses.append(response)

    assert [r.status_code for r in responses[:3]] == [201, 201, 201]
    assert responses[3].status_code == 429
    assert "Retry-After" in responses[3].headers

    # Prove the earlier successes were real (distinct idempotency keys => distinct
    # Pack rows), not idempotent replays of a single purchase.
    packs = db_session.scalars(select(Pack).where(Pack.user_id == user_id)).all()
    assert len(packs) == 3

    user = db_session.get(User, user_id)
    assert user.wallet_balance_cached == pack_type.price * 10 - pack_type.price * 3


def test_unauthenticated_purchase_returns_401_not_429(client, basic_odds_setup, monkeypatch):
    # Even with a tiny limit, an unauthenticated caller must fail auth (401) before
    # per-user rate limiting can even apply -- proving order-of-dependency correctness.
    monkeypatch.setattr(rate_limit, "PURCHASE_USER", parse("1/minute"))

    response = client.post(
        PURCHASE_URL,
        json={"pack_type_id": str(basic_odds_setup["pack_type"].id)},
        headers={"Idempotency-Key": "unauth-key"},
    )
    assert response.status_code == 401
