"""Citation guard — the hallucination guard (DESIGN.md §5 Phase 4).

"Post-generation, deterministically verify that every claim sentence maps to a
cited chunk_id present in MergedContext. Uncited or mis-cited claims are
stripped; if stripping leaves the report threadbare, regenerate up to 2x with a
tightened prompt, then fall back to an evidence-only structured summary."

Citations (not prose sentences) are the unit of verification: each `Citation`
in the model's structured output names a `chunk_id` it claims to be grounded
in. A citation whose chunk_id doesn't exist in the retrieved evidence is
stripped. "Threadbare" is judged on how many citations survive — surgically
removing specific sentences from free-form prose without fragile NLP is out of
scope; a threadbare report is regenerated or replaced by the evidence-only
fallback (which has no free prose to begin with, sidestepping the problem).
"""

from hailmary.schemas.contracts import Citation

MIN_SURVIVING_CITATIONS = 2


def verify_citations(citations: list[Citation], valid_chunk_ids: set[str]) -> list[Citation]:
    """Strip any citation whose chunk_id isn't in the retrieved evidence."""
    return [c for c in citations if c.chunk_id in valid_chunk_ids]


def is_threadbare(surviving_citations: list[Citation]) -> bool:
    return len(surviving_citations) < MIN_SURVIVING_CITATIONS
