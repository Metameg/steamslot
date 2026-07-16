"""Developer tool: refreshes data/catalog_seed.json from live Steam prices.

Run occasionally, never at seed/app-start time:
    uv run python scripts/refresh_catalog_fixture.py
"""

import json
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from app.catalog.steam_client import SteamFetchError, fetch_game

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog_seed.json"

# Curated app IDs spanning MVP price bands. See docs/design.md "Catalog Seeding".
# NOTE: verify each fetched title/price against the intended game when this script is run for
# real (Step 4) - a wrong app ID will either fail the fetch (skipped) or resolve to the wrong
# game, both visible in the printed output.
CURATED_APP_IDS = [
    # ~$1-5
    1794680,  # Vampire Survivors
    945360,  # Among Us
    # ~$5-15
    620,  # Portal 2
    105600,  # Terraria
    2379780,  # Balatro
    413150,  # Stardew Valley
    367520,  # Hollow Knight
    # ~$15-30
    1145360,  # Hades
    504230,  # Celeste
    268910,  # Cuphead
    1092790,  # Inscryption
    646570,  # Slay the Spire
    588650,  # Dead Cells
    753640,  # Outer Wilds
    # ~$30-50
    292030,  # The Witcher 3
    632470,  # Disco Elysium
    427520,  # Factorio
    294100,  # RimWorld
    553420,  # Tunic
    # ~$50-70
    1245620,  # Elden Ring
    1091500,  # Cyberpunk 2077
    1086940,  # Baldur's Gate 3
    1174180,  # Red Dead Redemption 2
    814380,  # Sekiro
]


def main() -> None:
    client = httpx.Client(timeout=10.0)
    fixture: list[dict] = []
    for appid in CURATED_APP_IDS:
        try:
            game = fetch_game(appid, client=client)
        except SteamFetchError as exc:
            print(f"skipping appid={appid}: {exc}")
            continue
        fixture.append(asdict(game))
        print(f"fetched {game.title} (${game.regular_price / 100:.2f})")
        time.sleep(0.5)  # politeness delay
    client.close()

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(fixture)} games to {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
