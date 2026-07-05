"""Load a fixture and report what a replay-mode pipeline would see.

DESIGN.md §5 Phase 0: replay mode is the deterministic, zero-external-calls demo
path. In M1 there is no indexer yet (that's M2), so this script's job is to prove
the fixture parses and the ReplayFeedClient serves it correctly — a smoke check.
From M2 onward this script is extended to actually push records into
Elasticsearch/Qdrant/Redis/Postgres (idempotent upserts), which is where "loading"
gains real side effects.
"""

import asyncio
import sys

from hailmary.clients.feeds.replay import FixtureData, ReplayFeedClient
from hailmary.config import get_settings


async def load(fixture_name: str) -> None:
    fixture = FixtureData(fixture_name)
    client = ReplayFeedClient(fixture)

    print(f"Loaded fixture '{fixture_name}', virtual_clock={fixture.virtual_clock.isoformat()}")

    for sport in ("nfl", "cfb"):
        stats = await client.get_stats(sport)
        docs = await client.get_semantic_docs(sport)
        print(f"  {sport}: {len(stats)} stat records, {len(docs)} semantic docs")

    for game in fixture.manifest["games"]:
        game_id = game["game_id"]
        odds = await client.get_odds(game_id)
        weather = await client.get_weather(game_id)
        print(f"  {game_id}: {len(odds)} odds snapshots, {len(weather)} weather records")

    entity_map = await client.get_entity_map()
    print(
        f"  entity map: {len(entity_map.team_aliases)} team aliases, "
        f"{len(entity_map.players)} player keys"
    )


if __name__ == "__main__":
    settings = get_settings()
    name = sys.argv[1] if len(sys.argv) > 1 else settings.fixture_name
    asyncio.run(load(name))
