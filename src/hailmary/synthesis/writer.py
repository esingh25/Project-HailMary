"""Phase 4 synthesis prose (DESIGN.md §5 Phase 4).

"Generate grounded prose (summary, matchup analysis, key factors, line-movement
narrative) from ranked_chunks only. Pass the chunks as the sole evidence
context; instruct the model to cite a chunk_id for every factual claim."
"""

from hailmary.clients.llm import LLMClient
from hailmary.schemas.contracts import RetrievedChunk
from hailmary.schemas.internal import DraftReportProse

WRITER_PROMPT_TEMPLATE = (
    "You are a football research analyst. Write a grounded research summary "
    "using ONLY the evidence chunks below — never use outside knowledge. Every "
    "factual claim must cite the chunk_id it came from in the `citations` "
    "list. If the evidence doesn't support a claim, omit it rather than "
    "guessing.\n\n"
    "User question: {query}\n\n"
    "Evidence chunks:\n{evidence}\n\n"
    "Write: summary (2-3 sentences), matchup_analysis (a paragraph), "
    "key_factors (a list of short bullet facts — injuries, weather, trends), "
    "line_movement (a sentence describing how the line has moved, if odds "
    "evidence is present), and citations (chunk_id per claim)."
)


def _render_evidence(chunks: list[RetrievedChunk]) -> str:
    return "\n".join(f"[{c.chunk_id}] ({c.source}) {c.content}" for c in chunks)


async def write_report_prose(
    llm: LLMClient,
    model: str,
    prompt_version: str,
    raw_text: str,
    chunks: list[RetrievedChunk],
) -> DraftReportProse:
    prompt = WRITER_PROMPT_TEMPLATE.format(query=raw_text, evidence=_render_evidence(chunks))
    return await llm.complete(model, prompt_version, prompt, response_model=DraftReportProse)
