import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Game, OddsBand


class NoEligibleGamesError(Exception):
    pass


@dataclass
class RollResult:
    band: OddsBand
    game: Game
    effective_probabilities: dict[str, float]


def eligible_games_for_band(db: Session, band: OddsBand) -> list[Game]:
    return list(
        db.scalars(
            select(Game).where(
                Game.is_eligible.is_(True),
                Game.regular_price >= band.min_price,
                Game.regular_price <= band.max_price,
            )
        )
    )


def roll(db: Session, bands: list[OddsBand]) -> RollResult:
    rng = secrets.SystemRandom()

    candidates: list[tuple[OddsBand, list[Game]]] = []
    for band in bands:
        games = eligible_games_for_band(db, band)
        if games:
            candidates.append((band, games))

    if not candidates:
        raise NoEligibleGamesError("no odds band has an eligible game in stock")

    total_weight = sum(float(band.probability) for band, _ in candidates)
    effective_probabilities = {
        str(band.id): float(band.probability) / total_weight for band, _ in candidates
    }

    roll_point = rng.random() * total_weight
    cumulative = 0.0
    chosen_band, chosen_games = candidates[-1]
    for band, games in candidates:
        cumulative += float(band.probability)
        if roll_point <= cumulative:
            chosen_band, chosen_games = band, games
            break

    chosen_game = rng.choice(chosen_games)
    return RollResult(band=chosen_band, game=chosen_game, effective_probabilities=effective_probabilities)


def expected_value(db: Session, bands: list[OddsBand]) -> float:
    """Average payout per pack given roll()'s actual behavior: bands with no eligible
    games are excluded and the remaining bands' weights re-normalized, exactly as roll() does.
    total_weight MUST be computed only over bands that have an eligible game -- computing it over
    all input bands (then skipping empty ones in the loop without adjusting the weight) silently
    understates EV whenever any band is out of stock, defeating the one function whose job is to
    prove the house edge holds."""
    candidates: list[tuple[OddsBand, list[Game]]] = []
    for band in bands:
        games = eligible_games_for_band(db, band)
        if games:
            candidates.append((band, games))

    total_weight = sum(float(band.probability) for band, _ in candidates)
    if total_weight == 0:
        return 0.0
    ev = 0.0
    for band, games in candidates:
        avg_band_value = sum(g.regular_price for g in games) / len(games)
        ev += (float(band.probability) / total_weight) * avg_band_value
    return ev
