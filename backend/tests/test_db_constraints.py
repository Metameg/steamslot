import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import User


FK_INDEXES = [
    ("ledger_entries", "user_id"),
    ("packs", "user_id"),
    ("pulls", "user_id"),
    ("odds_bands", "odds_table_id"),
    ("odds_tables", "pack_type_id"),
    ("redemption_requests", "user_id"),
    ("redemption_requests", "fulfilled_by"),
    ("withdrawals", "user_id"),
]


@pytest.mark.parametrize("table_name,column_name", FK_INDEXES)
def test_fk_column_is_indexed(engine, table_name, column_name):
    inspector = inspect(engine)
    indexes = inspector.get_indexes(table_name)
    assert any(
        column_name in idx["column_names"] for idx in indexes
    ), f"expected an index covering {table_name}.{column_name}, got indexes: {indexes}"


def test_wallet_balance_cannot_go_negative(db_session):
    user = User(
        email="wallet-check@example.com",
        display_name="Wallet Check",
        wallet_balance_cached=100,
    )
    db_session.add(user)
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE users SET wallet_balance_cached = -1 WHERE id = :id"),
            {"id": user.id},
        )
        db_session.flush()
