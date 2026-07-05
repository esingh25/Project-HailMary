"""Deterministic edge/EV math (DESIGN.md §5 Phase 4, §4 EdgeAnalysis).

Pure functions, no I/O. The LLM never produces these numbers — it narrates them.
"""

from hailmary.config import EdgeConfig
from hailmary.schemas.contracts import EdgeAnalysis, OddsSnapshot


def american_to_implied(american_odds: int) -> float:
    """Convert American odds to the market-implied win probability."""
    if american_odds < 0:
        return -american_odds / (-american_odds + 100)
    return 100 / (american_odds + 100)


def payout_per_unit_stake(american_odds: int) -> float:
    """Profit per $1 staked if the bet wins (excludes the returned stake)."""
    if american_odds < 0:
        return 100 / -american_odds
    return american_odds / 100


def expected_value_pct(model_probability: float, american_odds: int) -> float:
    """EV as a percentage of stake: p*payout - (1-p)*1, expressed as a percentage."""
    payout = payout_per_unit_stake(american_odds)
    ev = model_probability * payout - (1 - model_probability) * 1
    return ev * 100


def classify_assessment(ev_pct: float | None, config: EdgeConfig) -> str:
    if ev_pct is None:
        return "insufficient_data"
    if ev_pct >= config.ev_value_threshold_pct:
        return "value"
    if ev_pct <= config.ev_no_value_threshold_pct:
        return "no_value"
    return "fair"


# Markets the Elo power-rating heuristic covers (DESIGN.md §11 Decision Log #1, #8).
COVERED_MARKETS = {"spread", "moneyline"}


def build_edge_analysis(
    odds: OddsSnapshot,
    model_probability: float | None,
    config: EdgeConfig,
) -> EdgeAnalysis:
    """Build one EdgeAnalysis from a single odds snapshot + an optional model probability.

    `model_probability` must be None for markets outside the Elo heuristic's coverage
    (props, futures) — the caller is responsible for that gating; this function honestly
    returns `insufficient_data` whenever `model_probability` is None, regardless of market.
    """
    implied = american_to_implied(odds.price)

    if model_probability is None or odds.market not in COVERED_MARKETS:
        return EdgeAnalysis(
            market=odds.market,
            selection=odds.selection,
            american_odds=odds.price,
            implied_probability=implied,
            model_probability=None,
            expected_value_pct=None,
            assessment="insufficient_data",
        )

    ev_pct = expected_value_pct(model_probability, odds.price)
    assessment = classify_assessment(ev_pct, config)

    return EdgeAnalysis(
        market=odds.market,
        selection=odds.selection,
        american_odds=odds.price,
        implied_probability=implied,
        model_probability=model_probability,
        expected_value_pct=ev_pct,
        assessment=assessment,
    )
