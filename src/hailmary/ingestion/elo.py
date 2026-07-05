"""Nightly Elo ratings update (DESIGN.md §5 Phase 0, §13 Decision Log #8).

Pure function: takes a ratings snapshot + a batch of completed games, returns the
updated ratings. Standard Elo logistic expectation with a home-field constant and a
margin-of-victory multiplier (both config-tunable per DESIGN.md §5: "K-factor and
constants live in config").
"""

import math

from hailmary.config import EloConfig
from hailmary.schemas.internal import GameResult


def _expected_home_win_prob(
    home_rating: float, away_rating: float, home_field: float, logistic_scale: float
) -> float:
    diff = (home_rating + home_field) - away_rating
    return 1 / (1 + 10 ** (-diff / logistic_scale))


def update(
    ratings: dict[str, float],
    game_results: list[GameResult],
    config: EloConfig,
    default_rating: float = 1500.0,
) -> dict[str, float]:
    """Apply one batch of game results to a ratings snapshot, returning a new dict.

    Unlisted teams start at `default_rating`. Updates are zero-sum per game: what the
    winner gains, the loser loses.

    All games in one call must share a single sport — `ratings` is a flat
    `team_id -> rating` dict with no sport partition, so mixing sports in one batch
    would let colliding team_id abbreviations (e.g. "MIA" in both NFL and CFB)
    silently corrupt each other's ratings. Callers must invoke this once per sport.
    """
    if game_results:
        sports = {game.sport for game in game_results}
        if len(sports) > 1:
            raise ValueError(
                f"update() received games from multiple sports in one batch: {sports}. "
                "Call update() separately per sport — ratings are not sport-partitioned."
            )

    updated = dict(ratings)

    for game in game_results:
        home_rating = updated.get(game.home_team_id, default_rating)
        away_rating = updated.get(game.away_team_id, default_rating)

        expected_home = _expected_home_win_prob(
            home_rating, away_rating, config.home_field, config.logistic_scale
        )

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
