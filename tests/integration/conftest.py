"""Integration-tier fixtures: real dockerized stores + the committed fixture.

PLAN.md testing strategy: "Integration (dockerized stores + cassettes)." Each
test connects to the compose stack (docker/docker-compose.yml) and skips
cleanly when the stores are unreachable or unmigrated, so `pytest -m
integration` degrades to skips on a machine without the stack instead of
erroring.
"""

from types import SimpleNamespace

import pytest

from hailmary.clients.es import get_es_client
from hailmary.clients.feeds.replay import FixtureData
from hailmary.clients.postgres import get_pg_connection
from hailmary.clients.qdrant import get_qdrant_client
from hailmary.clients.redis import get_redis_client
from hailmary.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(replay_mode=True, replay_llm=True)


@pytest.fixture
def fixture_data(settings) -> FixtureData:
    return FixtureData(settings.fixture_name)


@pytest.fixture
async def stores(settings):
    es = get_es_client(settings)
    qdrant = get_qdrant_client(settings)
    redis_client = get_redis_client(settings)
    pg = None
    try:
        await es.info()
        await qdrant.get_collections()
        await redis_client.ping()
        pg = await get_pg_connection(settings)
        await pg.fetchval("SELECT COUNT(*) FROM schema_migrations")
    except Exception as exc:
        await es.close()
        await qdrant.close()
        await redis_client.aclose()
        if pg is not None:
            await pg.close()
        pytest.skip(
            f"dockerized stores unreachable/unmigrated ({exc!r}) — "
            "run `docker compose -f docker/docker-compose.yml up -d --wait` "
            "and `uv run python scripts/migrate.py`"
        )

    try:
        yield SimpleNamespace(es=es, qdrant=qdrant, redis=redis_client, pg=pg)
    finally:
        await es.close()
        await qdrant.close()
        await redis_client.aclose()
        await pg.close()
