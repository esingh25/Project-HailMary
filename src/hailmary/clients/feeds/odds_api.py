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


async def _consume_budget(pg, n: int, today: date) -> None:
    row = await pg.fetchrow(
        "SELECT source, period_start, calls_used, calls_limit FROM api_budget "
        "WHERE source = 'the_odds_api'"
    )
    if row is None:
        raise OddsBudgetExceededError("No api_budget row for the_odds_api — seed it first.")
    state, allowed = try_consume(BudgetState(**dict(row)), n, today)
    if not allowed:
        raise OddsBudgetExceededError(
            f"Odds API budget exhausted: {state.calls_used}/{state.calls_limit} this period."
        )
    await pg.execute(
        "UPDATE api_budget SET period_start = $1, calls_used = $2 WHERE source = 'the_odds_api'",
        state.period_start,
        state.calls_used,
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
    await _consume_budget(pg, 1, now.date())

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
    response.raise_for_status()
    events = response.json()
    return [s for event in events for s in snapshots_from_event(event, game_id, now)]
