"""Voyage embedding client with a cassette layer for deterministic, keyless replay.

Document embeddings for the synthetic_v0 fixture are precomputed and committed in
fixtures/synthetic_v0/embeddings.json (no API calls needed at all in replay mode for
document vectors). This client covers *query* embeddings, which vary per request and
so need the same cassette mechanism as the LLM client. Live-mode Voyage wiring lands
in M3 (Phase 2 semantic retrieval) once there is a query to embed.
"""

from pathlib import Path

from hailmary.clients.cassette import cassette_key, load_cassette, save_cassette
from hailmary.config import Settings


class VoyageClient:
    def __init__(self, settings: Settings, cassette_dir: Path):
        self._settings = settings
        self._cassette_dir = cassette_dir

    async def embed_query(self, model: str, text: str) -> list[float]:
        """Return the embedding vector for a query string. Replay mode reads from cassette."""
        if self._settings.replay_llm:
            key = cassette_key("voyage_embed", model, text)
            cassette = load_cassette(self._cassette_dir, key)
            return cassette["vector"]

        raise NotImplementedError("Live Voyage calls are wired in M3 (semantic retrieval).")

    def record(self, model: str, text: str, vector: list[float]) -> None:
        """Persist a cassette for (model, text) -> vector, once a Voyage key exists."""
        key = cassette_key("voyage_embed", model, text)
        save_cassette(self._cassette_dir, key, {"vector": vector})
