"""Odds API monthly budget guard (DESIGN.md §9, §6.4 api_budget table).

"A call that would exceed the budget is refused... Hard guard, not advisory." Pure
arithmetic core against a BudgetState snapshot; the Postgres-backed read/write wrapper
is added in M2 (ingestion/indexer.py) once the api_budget table is live.
"""

from datetime import date

from pydantic import BaseModel


class BudgetState(BaseModel):
    source: str
    period_start: date
    calls_used: int
    calls_limit: int


def _month_start(d: date) -> date:
    return d.replace(day=1)


def try_consume(state: BudgetState, n: int, today: date) -> tuple[BudgetState, bool]:
    """Attempt to consume `n` calls, rolling the period over if `today` is a new month.

    Returns (new_state, allowed). When allowed is False, the caller must not make the
    call and new_state reflects only the rollover (if any) — calls_used is unchanged.
    """
    current_period = _month_start(today)
    if state.period_start != current_period:
        state = state.model_copy(update={"period_start": current_period, "calls_used": 0})

    if state.calls_used + n > state.calls_limit:
        return state, False

    state = state.model_copy(update={"calls_used": state.calls_used + n})
    return state, True
