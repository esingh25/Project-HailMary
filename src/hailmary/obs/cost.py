"""LLM cost circuit breakers (DESIGN.md §9).

"Per-query LLM spend cap: $0.15/query, alert at $0.10. A query exceeding the
cap returns the deterministic evidence/edge block without full prose
synthesis." / "Per-day LLM cap: env-configurable (default $2/day), alert at
80% on the dashboard." Trackers are in-memory per-process; persisting daily
totals across restarts (for the dashboard, M7) is a follow-up — this module
covers the circuit-breaker decision itself.
"""

from dataclasses import dataclass, field

from hailmary.config import CostConfig


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    input_price_per_mtok: float,
    output_price_per_mtok: float,
) -> float:
    return (input_tokens / 1_000_000) * input_price_per_mtok + (
        output_tokens / 1_000_000
    ) * output_price_per_mtok


@dataclass
class QueryCostTracker:
    """Tracks spend for a single query's LLM calls (guardrail + extraction + synthesis)."""

    spent_usd: float = 0.0

    def add(self, usd: float) -> None:
        self.spent_usd += usd

    def exceeds_cap(self, config: CostConfig) -> bool:
        return self.spent_usd > config.per_query_usd_cap

    def exceeds_alert(self, config: CostConfig) -> bool:
        return self.spent_usd > config.per_query_usd_alert


@dataclass
class DailyCostTracker:
    """Tracks cumulative spend across all queries in a day."""

    spent_usd: float = field(default=0.0)

    def add(self, usd: float) -> None:
        self.spent_usd += usd

    def exceeds_cap(self, config: CostConfig) -> bool:
        return self.spent_usd > config.per_day_usd_cap

    def exceeds_alert(self, config: CostConfig) -> bool:
        return self.spent_usd > config.per_day_usd_cap * config.per_day_usd_alert_pct
