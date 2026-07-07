"""Elasticsearch client + index setup (DESIGN.md §6.1).

Single-node ES, organized by sport so only the relevant field set is queried.
"""

from elasticsearch import AsyncElasticsearch

from hailmary.config import Settings

NFL_STATS_INDEX = "nfl_stats"
CFB_STATS_INDEX = "cfb_stats"

# Mapping sketch (DESIGN.md §6.1), applied to both sport indexes.
STATS_MAPPING = {
    "properties": {
        "record_id": {"type": "keyword"},
        "season": {"type": "integer"},
        "week": {"type": "integer"},
        "team_id": {"type": "keyword"},
        "player_id": {"type": "keyword"},
        "game_id": {"type": "keyword"},
        "fields": {"type": "object"},
        "text_blob": {"type": "text"},
        "content_hash": {"type": "keyword"},
        "indexed_at": {"type": "date"},
    }
}


def index_name_for_sport(sport: str) -> str:
    if sport == "nfl":
        return NFL_STATS_INDEX
    if sport == "cfb":
        return CFB_STATS_INDEX
    raise ValueError(f"Unknown sport: {sport!r}")


def get_es_client(settings: Settings) -> AsyncElasticsearch:
    return AsyncElasticsearch(hosts=[settings.elasticsearch_host])


async def ensure_stats_indexes(client: AsyncElasticsearch) -> None:
    """Create both sport indexes with the shared mapping if they don't already exist."""
    for index in (NFL_STATS_INDEX, CFB_STATS_INDEX):
        if not await client.indices.exists(index=index):
            await client.indices.create(index=index, mappings=STATS_MAPPING)
