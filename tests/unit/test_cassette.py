"""Tests for the cassette read/write mechanism and the LLM/Voyage client wrappers."""

import pytest

from hailmary.clients.cassette import CassetteMissError, cassette_key, load_cassette, save_cassette
from hailmary.clients.llm import LLMClient
from hailmary.clients.voyage import VoyageClient
from hailmary.config import Settings
from hailmary.schemas.internal import GuardrailResult


@pytest.mark.unit
def test_cassette_key_is_deterministic_for_same_inputs():
    key1 = cassette_key("claude-haiku-4-5", "v1", "classify this query")
    key2 = cassette_key("claude-haiku-4-5", "v1", "classify this query")
    assert key1 == key2


@pytest.mark.unit
def test_cassette_key_differs_when_prompt_changes():
    key1 = cassette_key("claude-haiku-4-5", "v1", "prompt A")
    key2 = cassette_key("claude-haiku-4-5", "v1", "prompt B")
    assert key1 != key2


@pytest.mark.unit
def test_load_cassette_raises_loudly_on_miss(tmp_path):
    with pytest.raises(CassetteMissError):
        load_cassette(tmp_path, "nonexistent_key")


@pytest.mark.unit
def test_save_then_load_cassette_round_trips(tmp_path):
    key = cassette_key("model", "v1", "prompt")
    save_cassette(tmp_path, key, {"intent": "spread"})
    result = load_cassette(tmp_path, key)
    assert result == {"intent": "spread"}


@pytest.mark.unit
async def test_llm_client_replay_mode_hits_recorded_cassette(tmp_path):
    settings = Settings(_env_file=None, replay_llm=True)
    client = LLMClient(settings, tmp_path)
    client.record("claude-haiku-4-5", "v1", "classify: is this football?", {"intent": "spread"})

    result = await client.complete("claude-haiku-4-5", "v1", "classify: is this football?")
    assert result == {"intent": "spread"}


@pytest.mark.unit
async def test_llm_client_replay_mode_raises_loudly_on_prompt_change(tmp_path):
    settings = Settings(_env_file=None, replay_llm=True)
    client = LLMClient(settings, tmp_path)
    client.record("claude-haiku-4-5", "v1", "old prompt", {"intent": "spread"})

    with pytest.raises(CassetteMissError):
        await client.complete("claude-haiku-4-5", "v1", "new prompt after a prompt change")


@pytest.mark.unit
async def test_llm_client_live_mode_without_api_key_raises_clearly(tmp_path):
    settings = Settings(_env_file=None, replay_llm=False, gemini_api_key=None)
    client = LLMClient(settings, tmp_path)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await client.complete(
            "google/gemini-2.5-pro", "v1", "write a report", response_model=GuardrailResult
        )


@pytest.mark.unit
async def test_llm_client_live_mode_rejects_bare_model_ids(tmp_path):
    """Live calls must be provider-qualified (docs/AMENDMENTS.md A1); bare ids
    only exist as cassette keys."""
    settings = Settings(_env_file=None, replay_llm=False, gemini_api_key="fake-key")
    client = LLMClient(settings, tmp_path)
    with pytest.raises(ValueError, match="provider-qualified"):
        await client.complete(
            "claude-sonnet-4-6", "v1", "write a report", response_model=GuardrailResult
        )


@pytest.mark.unit
async def test_llm_client_live_mode_requires_a_response_model(tmp_path):
    settings = Settings(_env_file=None, replay_llm=False, anthropic_api_key="fake-key-for-test")
    client = LLMClient(settings, tmp_path)
    with pytest.raises(ValueError, match="response_model"):
        await client.complete("claude-sonnet-4-6", "v1", "write a report")


@pytest.mark.unit
async def test_voyage_client_replay_mode_hits_recorded_cassette(tmp_path):
    settings = Settings(_env_file=None, replay_llm=True)
    client = VoyageClient(settings, tmp_path)
    client.record("voyage-3", "is there value on KC -6.5?", [0.1, 0.2, 0.3])

    vector = await client.embed_query("voyage-3", "is there value on KC -6.5?")
    assert vector == [0.1, 0.2, 0.3]


@pytest.mark.unit
async def test_voyage_client_replay_mode_misses_on_unseen_query(tmp_path):
    settings = Settings(_env_file=None, replay_llm=True)
    client = VoyageClient(settings, tmp_path)
    with pytest.raises(CassetteMissError):
        await client.embed_query("voyage-3", "a query never recorded before")
