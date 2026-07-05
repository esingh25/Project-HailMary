"""Redis client factory (DESIGN.md §6.3 live-feed hot cache, §8 session memory)."""

import redis.asyncio as redis

from hailmary.config import Settings


def get_redis_client(settings: Settings) -> redis.Redis:
    return redis.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)


def odds_key(game_id: str, book: str, market: str, selection: str) -> str:
    return f"odds:{game_id}:{book}:{market}:{selection}"


def injury_key(player_id: str) -> str:
    return f"injury:{player_id}"


def weather_key(game_id: str) -> str:
    return f"weather:{game_id}"
