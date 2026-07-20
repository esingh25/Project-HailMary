"""LLM client with a cassette layer for deterministic, keyless replay.

DESIGN.md §5 Phases 1/4: a fast model (guardrail + extraction) and a strong
model (synthesis) are the only two LLM call sites in the system. Both go
through this client so replay mode is keyless and live mode is a single,
auditable call path.

Live mode routes through instructor.from_provider, so the configured model ids
must be provider-qualified (e.g. "google/gemini-2.5-flash",
"anthropic/claude-sonnet-4-6"). Replay cassettes key on the model string
as-recorded, so bare ids in existing cassettes keep replaying unchanged.
(Provider deviation from the frozen DESIGN.md — which names Anthropic — is
recorded in docs/AMENDMENTS.md.)
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

        if response_model is None:
            raise ValueError("Live LLM calls require a response_model for structured output.")
        if "/" not in model:
            raise ValueError(
                f"Live LLM calls need a provider-qualified model id like "
                f"'google/gemini-2.5-flash', got {model!r}. "
                "Set REPLAY_LLM=true to use recorded cassettes instead."
            )
        api_key = self._provider_key(model.split("/", 1)[0])

        import instructor

        client = instructor.from_provider(model, api_key=api_key, async_client=True)
        return await client.chat.completions.create(
            response_model=response_model,
            messages=[{"role": "user", "content": prompt}],
        )

    def _provider_key(self, provider: str) -> str:
        key = {
            "google": self._settings.gemini_api_key,
            "anthropic": self._settings.anthropic_api_key,
        }.get(provider)
        if not key:
            raise RuntimeError(
                f"No API key configured for provider {provider!r} "
                f"(set {'GEMINI' if provider == 'google' else provider.upper()}_API_KEY, "
                "or REPLAY_LLM=true for cassettes)."
            )
        return key

    def record(self, model: str, prompt_version: str, prompt: str, response: dict) -> None:
        """Persist a cassette for (model, prompt_version, prompt) -> response.

        Called by scripts/record_cassettes.py after a real API call, once the
        Anthropic key exists — not used in replay mode.
        """
        key = cassette_key(model, prompt_version, prompt)
        save_cassette(self._cassette_dir, key, response)
