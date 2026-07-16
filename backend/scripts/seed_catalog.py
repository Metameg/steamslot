"""Idempotent catalog seeder: upserts games from the committed fixture.

Run after migrations, no network access:
    uv run python scripts/seed_catalog.py
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Game

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog_seed.json"


def seed_catalog(db: Session, fixture_path: Path = FIXTURE_PATH) -> int:
    entries = json.loads(fixture_path.read_text())
    count = 0
    for entry in entries:
        game = db.scalar(select(Game).where(Game.steam_app_id == entry["steam_app_id"]))
        if game is None:
            game = Game(steam_app_id=entry["steam_app_id"])
            db.add(game)
        game.title = entry["title"]
        game.regular_price = entry["regular_price"]
        game.currency = entry["currency"]
        game.header_image_url = entry["header_image_url"]
        game.region = "US"
        game.is_eligible = True
        count += 1
    db.commit()
    return count


if __name__ == "__main__":
    with SessionLocal() as session:
        n = seed_catalog(session)
        print(f"seeded/updated {n} games")
