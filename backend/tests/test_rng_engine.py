from collections import Counter

import pytest

from app.models import Game
from app.services.rng_engine import NoEligibleGamesError, expected_value, roll


def test_roll_distribution_matches_published_odds(db_session, basic_odds_setup):
    bands = basic_odds_setup["bands"]
    counts = Counter()
    n = 4000
    for _ in range(n):
        result = roll(db_session, bands)
        counts[result.band.name] += 1

    assert abs(counts["Common"] / n - 0.70) < 0.03
    assert abs(counts["Rare"] / n - 0.25) < 0.03
    assert abs(counts["Grail"] / n - 0.05) < 0.02


def test_roll_picks_game_within_band_price_range(db_session, basic_odds_setup):
    bands = basic_odds_setup["bands"]
    for _ in range(200):
        result = roll(db_session, bands)
        assert result.band.min_price <= result.game.regular_price <= result.band.max_price


def test_roll_excludes_empty_band_and_renormalizes(db_session, basic_odds_setup):
    bands = basic_odds_setup["bands"]
    grail_game = db_session.query(Game).filter_by(title="Grail Game").one()
    grail_game.is_eligible = False
    db_session.flush()

    for _ in range(100):
        result = roll(db_session, bands)
        assert result.band.name != "Grail"


def test_roll_raises_when_no_games_eligible(db_session, basic_odds_setup):
    for game in db_session.query(Game).all():
        game.is_eligible = False
    db_session.flush()

    with pytest.raises(NoEligibleGamesError):
        roll(db_session, basic_odds_setup["bands"])


def test_expected_value_below_pack_price(db_session, basic_odds_setup):
    pack_type = basic_odds_setup["pack_type"]
    bands = basic_odds_setup["bands"]
    ev = expected_value(db_session, bands)
    # 0.70*300 + 0.25*900 + 0.05*5000 = 210 + 225 + 250 = 685
    assert ev == pytest.approx(685, abs=1)
    assert ev < pack_type.price
