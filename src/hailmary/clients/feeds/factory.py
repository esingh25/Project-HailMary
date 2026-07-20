"""FeedClient factory — the single place REPLAY_MODE picks an implementation
(DESIGN.md §5 Phase 0: "no phase code checks REPLAY_MODE directly except the
factory").

Live mode composes the per-source feeds behind the same FeedClient protocol:
nflverse (stats/injuries/results/entity map), CFBD (cfb stats/results, inert
without a key), curated scraper (prose docs). Odds and weather need per-game
context the protocol doesn't carry (API event ids, venue coordinates), so the
M8 live scheduler calls clients.feeds.odds_api / open_meteo directly; through
this protocol surface they return empty.
"""

import httpx

from hailmary.clients.feeds.cfbd import CfbdFeed
from hailmary.clients.feeds.nflverse import NflverseFeed
from hailmary.clients.feeds.replay import FixtureData, ReplayFeedClient
from hailmary.clients.feeds.scraper import fetch_docs
from hailmary.config import Settings
from hailmary.schemas.internal import EntityMap


class LiveFeedClient:
    def __init__(self, settings: Settings, season: int, scrape_sources: list[dict] | None = None):
        self._http = httpx.AsyncClient()
        self._nfl = NflverseFeed(season)
        self._cfb = CfbdFeed(settings, season, self._http)
        self._scrape_sources = scrape_sources or []

    async def get_stats(self, sport: str):
        if sport == "cfb":
            return await self._cfb.get_stats(sport)
        return await self._nfl.get_stats(sport)

    async def get_semantic_docs(self, sport: str):
        sources = [s for s in self._scrape_sources if s["sport"] == sport]
        return await fetch_docs(sources, self._http)

    async def get_odds(self, game_id: str):
        return []  # wired per-game by the live scheduler via feeds.odds_api

    async def get_injuries(self, team_id: str):
        return await self._nfl.get_injuries(team_id)

    async def get_weather(self, game_id: str):
        return []  # wired per-game by the live scheduler via feeds.open_meteo

    async def get_game_results(self, sport: str):
        if sport == "cfb":
            return await self._cfb.get_game_results(sport)
        return await self._nfl.get_game_results(sport)

    async def get_entity_map(self) -> EntityMap:
        return await self._nfl.get_entity_map()

    async def aclose(self) -> None:
        await self._http.aclose()


def get_feed_client(settings: Settings, season: int):
    if settings.replay_mode:
        return ReplayFeedClient(FixtureData(settings.fixture_name))
    return LiveFeedClient(settings, season)
