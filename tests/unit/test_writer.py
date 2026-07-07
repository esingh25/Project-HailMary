"""Tests for the Phase 4 synthesis prose call site."""

from datetime import UTC, datetime

import pytest

from hailmary.schemas.contracts import Citation, RetrievedChunk
from hailmary.schemas.internal import DraftReportProse
from hailmary.synthesis.writer import write_report_prose

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakeLLMClient:
    def __init__(self, response):
        self._response = response
        self.calls: list[tuple] = []

    async def complete(self, model, prompt_version, prompt, response_model=None):
        self.calls.append((model, prompt_version, prompt, response_model))
        return self._response


def make_chunk(chunk_id="c1", content="KC averages 28 points per game"):
    return RetrievedChunk(
        chunk_id=chunk_id,
        source="stats_es",
        content=content,
        structured_data=None,
        index_score=0.9,
        freshness_ts=NOW,
        retrieved_at=NOW,
    )


@pytest.mark.unit
async def test_write_report_prose_returns_draft():
    draft = DraftReportProse(
        summary="KC is favored.",
        matchup_analysis="KC's offense is strong.",
        key_factors=["Mahomes probable"],
        line_movement="Opened -6.0, now -6.5",
        citations=[Citation(claim="KC averages 28 points", chunk_id="c1", source="stats_es")],
    )
    llm = FakeLLMClient(draft)

    result = await write_report_prose(
        llm, "claude-sonnet-4-6", "v1", "Is there value on KC -6.5?", [make_chunk()]
    )

    assert result.summary == "KC is favored."
    assert result.citations[0].chunk_id == "c1"


@pytest.mark.unit
async def test_write_report_prose_renders_every_chunk_into_the_prompt():
    draft = DraftReportProse(
        summary="s", matchup_analysis="m", key_factors=[], line_movement="l", citations=[]
    )
    llm = FakeLLMClient(draft)
    chunks = [make_chunk("c1", "content one"), make_chunk("c2", "content two")]

    await write_report_prose(llm, "claude-sonnet-4-6", "v1", "query", chunks)

    prompt = llm.calls[0][2]
    assert "[c1]" in prompt
    assert "[c2]" in prompt
    assert "content one" in prompt
    assert "content two" in prompt


@pytest.mark.unit
async def test_write_report_prose_requests_correct_response_model():
    draft = DraftReportProse(
        summary="s", matchup_analysis="m", key_factors=[], line_movement="l", citations=[]
    )
    llm = FakeLLMClient(draft)
    await write_report_prose(llm, "claude-sonnet-4-6", "v1", "query", [])
    assert llm.calls[0][3] is DraftReportProse
