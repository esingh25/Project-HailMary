"""Nightly Elo ratings update (DESIGN.md §5 Phase 0, §13 Decision Log #8).

Pure function: takes a ratings snapshot + a batch of completed games, returns the
updated ratings. Standard Elo logistic expectation with a home-field constant and a
margin-of-victory multiplier (both config-tunable per DESIGN.md §5: "K-factor and
constants live in config").
"""

import math

from hailmary.config import EloConfig
from hailmary.schemas.internal import GameResult


def _expected_home_win_prob(home_rating: float, away_rating: float, home_field: float) -> float:
    diff = (home_rating + home_field) - away_rating
    return 1 / (1 + 10 ** (-diff / 400))


def update(
    ratings: dict[str, float],
    game_results: list[GameResult],
    config: EloConfig,
    default_rating: float = 1500.0,
) -> dict[str, float]:
    """Apply one batch of game results to a ratings snapshot, returning a new dict.

    Unlisted teams start at `default_rating`. Updates are zero-sum per game: what the
    winner gains, the loser loses.
    """
    updated = dict(ratings)

    for game in game_results:
        home_rating = updated.get(game.home_team_id, default_rating)
        away_rating = updated.get(game.away_team_id, default_rating)

        expected_home = _expected_home_win_prob(home_rating, away_rating, config.home_field)

        if game.home_score > game.away_score:
            actual_home = 1.0
        elif game.home_score < game.away_score:
            actual_home = 0.0
        else:
            actual_home = 0.5

        margin = abs(game.home_score - game.away_score)
        mov_factor = 1.0 + config.mov_multiplier * math.log(1 + margin)

        delta = config.k * mov_factor * (actual_home - expected_home)

        updated[game.home_team_id] = home_rating + delta
        updated[game.away_team_id] = away_rating - delta

    return updated
