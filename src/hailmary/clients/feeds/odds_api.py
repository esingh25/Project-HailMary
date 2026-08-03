"""The Odds API live feed (DESIGN.md §5 Phase 0, §9) — 500 req/month free tier.

Every call goes through the hard budget guard: the api_budget row is read,
try_consume decides, and a refusal raises before any HTTP happens. The client
is additionally disabled unless ODDS_API_ENABLED=true — all pre-season dev
runs on the fixture (risk register #1).
"""

from datetime import UTC, date, datetime

import httpx

from hailmary.config import Settings
from hailmary.ingestion.budget import BudgetState, try_consume
from hailmary.schemas.contracts import OddsSnapshot

API_URL = "https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
SPORT_KEYS = {"nfl": "americanfootball_nfl", "cfb": "americanfootball_ncaaf"}
MARKET_NAMES = {"spreads": "spread", "h2h": "moneyline", "totals": "total"}


class OddsBudgetExceededError(Exception):
    """Raised instead of making a call that would blow the monthly budget."""


def snapshots_from_event(event: dict, game_id: str, captured_at: datetime) -> list[OddsSnapshot]:
    """Shape one Odds API event (bookmakers -> markets -> outcomes) into rows."""
    snapshots = []
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            market_name = MARKET_NAMES.get(market["key"])
            if market_name is None:
                continue
            for outcome in market.get("outcomes", []):
                snapshots.append(
                    OddsSnapshot(
                        game_id=game_id,
                        book=bookmaker["key"],
                        market=market_name,
                        selection=_selection(market_name, outcome),
                        line=outcome.get("point"),
                        price=int(outcome["price"]),
                        captured_at=captured_at,
                    )
                )
    return snapshots


def _selection(market_name: str, outcome: dict) -> str:
    point = outcome.get("point")
    if market_name == "spread" and point is not None:
        return f"{outcome['name']} {point:+g}"
    if market_name == "total" and point is not None:
        return f"{outcome['name']} {point:g}"
    return outcome["name"]


BUDGET_CAS_ATTEMPTS = 3


def _rows_updated(status: object) -> int:
    """Parse asyncpg's command tag ('UPDATE 1') into a row count.

    Deliberately strict: a driver or test double that returns something else
    must fail loudly rather than be read as a successful write, because the
    return value is what decides whether a paid API call is allowed.
    """
    if isinstance(status, str) and status.startswith("UPDATE "):
        return int(status.rsplit(" ", 1)[1])
    raise RuntimeError(f"Unexpected UPDATE status from the database driver: {status!r}")


async def _consume_budget(pg, n: int, today: date) -> None:
    """Atomically reserve `n` calls against the hard monthly cap.

    The read-decide-write cycle is guarded by a compare-and-swap: the UPDATE
    only lands if `period_start` and `calls_used` still hold the values the
    decision was computed from. If a concurrent consumer slips in between, the
    UPDATE matches zero rows and we re-read and re-decide.

    Without the CAS this is a plain read-check-write race, and it is not
    theoretical: two callers at 499/500 both pass try_consume, both make the
    paid call, and both write 500 — one increment silently lost and the cap
    ("hard guard, not advisory", DESIGN.md §9) quietly exceeded. A per-game
    fan-out over upcoming games is exactly that shape.

    The arithmetic stays in budget.try_consume; this function only makes
    applying it atomic.
    """
    for _ in range(BUDGET_CAS_ATTEMPTS):
        row = await pg.fetchrow(
            "SELECT source, period_start, calls_used, calls_limit FROM api_budget "
            "WHERE source = 'the_odds_api'"
        )
        if row is None:
            raise OddsBudgetExceededError("No api_budget row for the_odds_api — seed it first.")

        observed = BudgetState(**dict(row))
        state, allowed = try_consume(observed, n, today)
        if not allowed:
            raise OddsBudgetExceededError(
                f"Odds API budget exhausted: {state.calls_used}/{state.calls_limit} this period."
            )

        status = await pg.execute(
            "UPDATE api_budget SET period_start = $1, calls_used = $2 "
            "WHERE source = 'the_odds_api' AND period_start = $3 AND calls_used = $4",
            state.period_start,
            state.calls_used,
            observed.period_start,
            observed.calls_used,
        )
        if _rows_updated(status) == 1:
            return
        # Zero rows: someone else consumed between our read and write. Re-read.

    raise OddsBudgetExceededError(
        f"Could not reserve Odds API budget after {BUDGET_CAS_ATTEMPTS} attempts under "
        "contention. Refusing rather than risking an over-cap call."
    )


async def _refund_budget(pg, n: int, period_start: date) -> None:
    """Give back `n` reserved calls after a request that never reached the vendor.

    A relative decrement is atomic on its own, so no CAS is needed. Guarded on
    `period_start` so a refund can never reach into a rolled-over period, and on
    `calls_used >= n` so it can never drive the counter negative.
    """
    await pg.execute(
        "UPDATE api_budget SET calls_used = calls_used - $1 "
        "WHERE source = 'the_odds_api' AND period_start = $2 AND calls_used >= $1",
        n,
        period_start,
    )


async def fetch_odds(
    sport: str,
    game_id: str,
    api_event_id: str,
    settings: Settings,
    pg,
    client: httpx.AsyncClient,
) -> list[OddsSnapshot]:
    if not settings.odds_api_enabled:
        return []
    if not settings.odds_api_key:
        raise RuntimeError("ODDS_API_ENABLED is true but ODDS_API_KEY is not set.")

    now = datetime.now(UTC)
    # Reserve before calling, never after: deciding on a stale count is how a
    # cap gets exceeded. The cost of reserving first is that a request which
    # never reaches the vendor would burn a slot, so that case is compensated
    # below rather than left to leak budget on every transient network fault.
    await _consume_budget(pg, 1, now.date())

    try:
        response = await client.get(
            API_URL.format(sport_key=SPORT_KEYS[sport]),
            params={
                "apiKey": settings.odds_api_key,
                "regions": "us",
                "markets": "spreads,h2h,totals",
                "oddsFormat": "american",
                "eventIds": api_event_id,
            },
            timeout=10.0,
        )
    except httpx.RequestError:
        # No response was ever received (DNS, refused connection, TLS, timeout),
        # so the vendor did not count this against our quota either. Refund.
        # An HTTPStatusError is deliberately NOT refunded — that request did
        # reach the vendor and does count.
        try:
            await _refund_budget(pg, 1, now.date().replace(day=1))
        except Exception:  # noqa: BLE001 - a failed refund must not mask the transport error
            pass
        raise

    response.raise_for_status()
    events = response.json()
    return [s for event in events for s in snapshots_from_event(event, game_id, now)]
