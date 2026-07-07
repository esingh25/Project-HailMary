"""Elo-diff + home-field logistic mapping to a model win probability.

DESIGN.md §5 Phase 4: "for spreads and moneylines, derive model_probability from the
Elo rating difference + home field via a logistic mapping (constants in config,
documented)." Pure function, no I/O.
"""

from hailmary.config import EloConfig


def win_probability(
    team_rating: float,
    opponent_rating: float,
    is_home: bool,
    config: EloConfig,
    logistic_scale: float,
) -> float:
    """Standard Elo logistic: P(team wins) given the rating gap (+ home field bonus)."""
    home_bonus = config.home_field if is_home else 0.0
    rating_diff = (team_rating + home_bonus) - opponent_rating
    return 1 / (1 + 10 ** (-rating_diff / logistic_scale))
