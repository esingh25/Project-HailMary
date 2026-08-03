"""Query-embedding client with a cassette layer for deterministic, keyless replay.

Live embeddings go through Google Gemini, not Voyage (docs/AMENDMENTS.md A1). The
class name, the `voyage_embed` cassette prefix, and the `voyage_model` setting are
retained deliberately: the cassette key includes the model string as recorded, so
renaming them would invalidate every committed cassette for no behavioural gain.
Renaming is deferred (FINISH_PLAN.md F1).

Document embeddings for the synthetic_v0 fixture are precomputed and committed in
fixtures/synthetic_v0/embeddings.json (no API calls needed at all in replay mode for
document vectors). This client covers *query* embeddings, which vary per request and
so need the same cassette mechanism as the LLM client.
"""

from pathlib import Path

from hailmary.clients.cassette import cassette_key, load_cassette, save_cassette
from hailmary.config import Settings


class VoyageClient:
    def __init__(self, settings: Settings, cassette_dir: Path):
        self._settings = settings
        self._cassette_dir = cassette_dir

    async def embed_query(self, model: str, text: str) -> list[float]:
        """Return the embedding vector for a query string. Replay mode reads from
        cassette; live mode embeds via Gemini (docs/AMENDMENTS.md provider note).

        Caution: query and document vectors must come from the same embedding
        scheme for cosine scores to mean anything — going live means re-embedding
        the document corpus with the same model, not just flipping this path.
        """
        if self._settings.replay_llm:
            key = cassette_key("voyage_embed", model, text)
            cassette = load_cassette(self._cassette_dir, key)
            return cassette["vector"]

        if not self._settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set; cannot embed live. "
                "Set REPLAY_LLM=true to use recorded cassettes instead."
            )

        from google import genai

        client = genai.Client(api_key=self._settings.gemini_api_key)
        result = await client.aio.models.embed_content(model=model, contents=text)
        return list(result.embeddings[0].values)

    def record(self, model: str, text: str, vector: list[float]) -> None:
        """Persist a cassette for (model, text) -> vector, once GEMINI_API_KEY is set."""
        key = cassette_key("voyage_embed", model, text)
        save_cassette(self._cassette_dir, key, {"vector": vector})
