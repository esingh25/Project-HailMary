"""Anthropic LLM client with a cassette layer for deterministic, keyless replay.

DESIGN.md §5 Phases 1/4: Haiku (guardrail + extraction) and Sonnet (synthesis)
are the only two LLM call sites in the system. Both go through this client so
replay mode is keyless and live mode is a single, auditable call path.
"""

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from hailmary.clients.cassette import cassette_key, load_cassette, save_cassette
from hailmary.config import Settings

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LLMClient:
    def __init__(self, settings: Settings, cassette_dir: Path):
        self._settings = settings
        self._cassette_dir = cassette_dir

    async def complete(
        self,
        model: str,
        prompt_version: str,
        prompt: str,
        response_model: type[ResponseModel] | None = None,
    ) -> ResponseModel | dict:
        """Return a structured LLM response.

        Replay mode reads from a recorded cassette (validated against
        `response_model` when given, else returned as a raw dict). Live mode
        calls Anthropic via `instructor` for schema-validated structured output —
        `response_model` is required in live mode, since there's no schema-free
        way to get structured output from a real API call.
        """
        if self._settings.replay_llm:
            key = cassette_key(model, prompt_version, prompt)
            data = load_cassette(self._cassette_dir, key)
            return response_model.model_validate(data) if response_model else data

        if not self._settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; cannot make a live LLM call. "
                "Set REPLAY_LLM=true to use recorded cassettes instead."
            )
        if response_model is None:
            raise ValueError("Live LLM calls require a response_model for structured output.")

        import instructor
        from anthropic import AsyncAnthropic

        client = instructor.from_anthropic(AsyncAnthropic(api_key=self._settings.anthropic_api_key))
        return await client.messages.create(
            model=model,
            response_model=response_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

    def record(self, model: str, prompt_version: str, prompt: str, response: dict) -> None:
        """Persist a cassette for (model, prompt_version, prompt) -> response.

        Called by scripts/record_cassettes.py after a real API call, once the
        Anthropic key exists — not used in replay mode.
        """
        key = cassette_key(model, prompt_version, prompt)
        save_cassette(self._cassette_dir, key, response)
