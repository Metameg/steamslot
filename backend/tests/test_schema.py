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
