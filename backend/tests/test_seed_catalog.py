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
