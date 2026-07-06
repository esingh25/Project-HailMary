"""FastAPI delivery app (DESIGN.md §5 Phase 5).

Localhost-only API. Real client construction happens in the lifespan handler;
tests build the app with `lifespan=None` and populate `app.state` with fakes
directly — no dependency-override machinery needed for a single-process,
single-set-of-clients app this size.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from hailmary.clients.es import get_es_client
from hailmary.clients.feeds.replay import FixtureData
from hailmary.clients.llm import LLMClient
from hailmary.clients.postgres import get_pg_connection
from hailmary.clients.qdrant import get_qdrant_client
from hailmary.clients.redis import get_redis_client
from hailmary.clients.voyage import VoyageClient
from hailmary.config import get_settings
from hailmary.delivery.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    fixture = FixtureData(settings.fixture_name) if settings.replay_mode else None
    cassette_dir = fixture.dir / "llm_cassettes" if fixture else None

    app.state.settings = settings
    app.state.entity_map = fixture.entity_map if fixture else None
    app.state.now = fixture.virtual_clock if fixture else None
    app.state.llm = LLMClient(settings, cassette_dir)
    app.state.voyage = VoyageClient(settings, cassette_dir)
    app.state.es_client = get_es_client(settings)
    app.state.qdrant_client = get_qdrant_client(settings)
    app.state.redis_client = get_redis_client(settings)
    app.state.pg = await get_pg_connection(settings)

    yield

    await app.state.es_client.close()
    await app.state.qdrant_client.close()
    await app.state.redis_client.aclose()
    await app.state.pg.close()


STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(lifespan_fn: Callable | None = lifespan) -> FastAPI:
    app = FastAPI(title="HailMaryRAG", docs_url="/docs", lifespan=lifespan_fn)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def chat_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "chat.html")

    return app


app = create_app()

# DESIGN.md §5 Phase 5: "No public network binding — API and dashboard are
# localhost-only." Enforced at the ASGI-server invocation, not in-process:
#   uv run uvicorn hailmary.delivery.app:app --host 127.0.0.1 --port 8000
