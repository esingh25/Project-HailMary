"""Anthropic LLM client with a cassette layer for deterministic, keyless replay.

Live-mode instructor/Anthropic wiring (cost meter, circuit breaker) is built in M5
(Phase 1 decomposition) and M6 (Phase 4 synthesis) once those phases exist to call
it. This module builds the cassette read/write path now so CI can run keyless from
the moment any LLM-calling phase lands.
"""

from pathlib import Path

from hailmary.clients.cassette import cassette_key, load_cassette, save_cassette
from hailmary.config import Settings


class LLMClient:
    def __init__(self, settings: Settings, cassette_dir: Path):
        self._settings = settings
        self._cassette_dir = cassette_dir

    async def complete(self, model: str, prompt_version: str, prompt: str) -> dict:
        """Return a structured LLM response. Replay mode reads from a recorded cassette."""
        if self._settings.replay_llm:
            key = cassette_key(model, prompt_version, prompt)
            return load_cassette(self._cassette_dir, key)

        raise NotImplementedError(
            "Live Anthropic calls are wired in M5 (decomposition) / M6 (synthesis)."
        )

    def record(self, model: str, prompt_version: str, prompt: str, response: dict) -> None:
        """Persist a cassette for (model, prompt_version, prompt) -> response.

        Called by scripts/record_cassettes.py after a real API call, once the
        Anthropic key exists (M5+) — not used in replay mode.
        """
        key = cassette_key(model, prompt_version, prompt)
        save_cassette(self._cassette_dir, key, response)
