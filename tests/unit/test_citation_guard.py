"""Tests for the citation guard: verify/strip and threadbare detection."""

import pytest

from hailmary.schemas.contracts import Citation
from hailmary.synthesis.citation_guard import is_threadbare, verify_citations


def make_citation(chunk_id="c1"):
    return Citation(claim="some claim", chunk_id=chunk_id, source="stats_es")


@pytest.mark.unit
def test_verify_citations_keeps_valid_chunk_ids():
    citations = [make_citation("c1"), make_citation("c2")]
    result = verify_citations(citations, valid_chunk_ids={"c1", "c2"})
    assert len(result) == 2


@pytest.mark.unit
def test_verify_citations_strips_hallucinated_chunk_ids():
    citations = [make_citation("c1"), make_citation("hallucinated_id")]
    result = verify_citations(citations, valid_chunk_ids={"c1"})
    assert len(result) == 1
    assert result[0].chunk_id == "c1"


@pytest.mark.unit
def test_verify_citations_empty_input_returns_empty():
    assert verify_citations([], valid_chunk_ids={"c1"}) == []


@pytest.mark.unit
def test_is_threadbare_below_minimum():
    assert is_threadbare([make_citation("c1")]) is True
    assert is_threadbare([]) is True


@pytest.mark.unit
def test_is_threadbare_at_or_above_minimum():
    assert is_threadbare([make_citation("c1"), make_citation("c2")]) is False
    assert is_threadbare([make_citation("c1"), make_citation("c2"), make_citation("c3")]) is False
