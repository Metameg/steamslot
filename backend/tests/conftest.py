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
