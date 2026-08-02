"""Phase 4 orchestration: synthesis & edge analysis (DESIGN.md §5 Phase 4).

Deterministic edge math runs first, before any prose generation, and the LLM
never computes a number. Prose is generated from ranked_chunks only and passed
through the citation guard, regenerating up to 2x, falling back to an
evidence-only structured summary if still threadbare. The report leads with
evidence — the edge block is the last, supplementary section, never a verdict.

model_probability mapping simplification: DESIGN.md specifies the Elo-diff +
home-field logistic mapping but not how to match a specific odds selection
string (e.g. "KC -6.5") back to "which team's probability." This treats the
first team in the resolved entities as the matchup's subject team — a
documented simplification, not a doc requirement; a real selection-string
parser is future work.
"""

from datetime import datetime

from hailmary.clients.llm import LLMClient
from hailmary.config import EdgeConfig, EloConfig
from hailmary.schemas.contracts import (
    EdgeAnalysis,
    MergedContext,
    OddsSnapshot,
    QueryEntities,
    ResearchReport,
    RetrievedChunk,
)
from hailmary.synthesis.citation_guard import is_threadbare, verify_citations
from hailmary.synthesis.edge_math import build_edge_analysis
from hailmary.synthesis.elo_prob import win_probability
from hailmary.synthesis.writer import write_report_prose

RESPONSIBLE_GAMING_NOTICE = (
    "This report is for informational research purposes only and is not financial "
    "or betting advice. It surfaces evidence and math; it does not recommend "
    "placing any wager. If you or someone you know has a gambling problem, call or "
    "text 1-800-GAMBLER."
)

MAX_REGENERATIONS = 2


def _model_probability_for_matchup(
    entities: QueryEntities,
    team_ratings: dict[str, float],
    home_team_id: str | None,
    elo_config: EloConfig,
) -> float | None:
    if len(entities.teams) != 2:
        return None
    subject, opponent = entities.teams[0], entities.teams[1]
    # No default rating. If either side is unrated the Elo difference is not
    # knowable, and a nominal 1500-vs-1500 stand-in would not be a neutral
    # answer — it collapses to home field alone, which prices out as a real
    # edge on whichever team happens to be at home. Returning None makes
    # build_edge_analysis emit assessment="insufficient_data" instead.
    subject_rating = team_ratings.get(subject)
    opponent_rating = team_ratings.get(opponent)
    if subject_rating is None or opponent_rating is None:
        return None
    is_home = home_team_id == subject if home_team_id else False
    return win_probability(
        subject_rating,
        opponent_rating,
        is_home,
        elo_config,
        elo_config.logistic_scale,
    )


def _build_edge_analyses(
    ranked_chunks: list[RetrievedChunk],
    entities: QueryEntities,
    team_ratings: dict[str, float],
    home_team_id: str | None,
    elo_config: EloConfig,
    edge_config: EdgeConfig,
) -> list[EdgeAnalysis]:
    model_probability = _model_probability_for_matchup(
        entities, team_ratings, home_team_id, elo_config
    )
    blocks = []
    for chunk in ranked_chunks:
        if chunk.source != "live_odds" or not chunk.structured_data:
            continue
        odds = OddsSnapshot.model_validate(chunk.structured_data)
        blocks.append(build_edge_analysis(odds, model_probability, edge_config))
    return blocks


def _freshest_odds_timestamp(ranked_chunks: list[RetrievedChunk], fallback: datetime) -> datetime:
    odds_ts = [c.freshness_ts for c in ranked_chunks if c.source == "live_odds"]
    return max(odds_ts) if odds_ts else fallback


def _evidence_only_fallback(
    query_id: str,
    ranked_chunks: list[RetrievedChunk],
    edge_analysis: list[EdgeAnalysis],
    line_as_of: datetime,
    replay_mode: bool,
    sources_unavailable: list[str],
    model_version: str,
    prompt_version: str,
    now: datetime,
) -> ResearchReport:
    """No free prose — a plain structured listing of the evidence itself.
    Used when the citation guard can't ground generated prose after
    MAX_REGENERATIONS attempts (DESIGN.md Appendix A)."""
    key_factors = [c.content for c in ranked_chunks if c.source in ("live_injury", "weather")]
    return ResearchReport(
        query_id=query_id,
        summary="Evidence-only summary: grounded prose could not be generated for this query.",
        matchup_analysis="See key_factors and citations for the retrieved evidence.",
        key_factors=key_factors,
        line_movement="See citations for odds evidence.",
        edge_analysis=edge_analysis,
        citations=[],
        line_as_of=line_as_of,
        sources_unavailable=sources_unavailable,
        responsible_gaming_notice=RESPONSIBLE_GAMING_NOTICE,
        replay_mode=replay_mode,
        generated_at=now,
        model_version=model_version,
        prompt_version=prompt_version,
    )


async def build_report(
    query_id: str,
    raw_text: str,
    entities: QueryEntities,
    merged: MergedContext,
    team_ratings: dict[str, float],
    home_team_id: str | None,
    llm: LLMClient,
    sonnet_model: str,
    prompt_version: str,
    elo_config: EloConfig,
    edge_config: EdgeConfig,
    replay_mode: bool,
    sources_unavailable: list[str],
    now: datetime,
    pg=None,
) -> ResearchReport:
    edge_analysis = _build_edge_analyses(
        merged.ranked_chunks, entities, team_ratings, home_team_id, elo_config, edge_config
    )
    line_as_of = _freshest_odds_timestamp(merged.ranked_chunks, now)
    valid_chunk_ids = {c.chunk_id for c in merged.ranked_chunks}

    report: ResearchReport | None = None
    for _attempt in range(MAX_REGENERATIONS + 1):
        draft = await write_report_prose(
            llm, sonnet_model, prompt_version, raw_text, merged.ranked_chunks
        )
        surviving_citations = verify_citations(draft.citations, valid_chunk_ids)

        if not is_threadbare(surviving_citations):
            report = ResearchReport(
                query_id=query_id,
                summary=draft.summary,
                matchup_analysis=draft.matchup_analysis,
                key_factors=draft.key_factors,
                line_movement=draft.line_movement,
                edge_analysis=edge_analysis,
                citations=surviving_citations,
                line_as_of=line_as_of,
                sources_unavailable=sources_unavailable,
                responsible_gaming_notice=RESPONSIBLE_GAMING_NOTICE,
                replay_mode=replay_mode,
                generated_at=now,
                model_version=sonnet_model,
                prompt_version=prompt_version,
            )
            break

    if report is None:
        report = _evidence_only_fallback(
            query_id,
            merged.ranked_chunks,
            edge_analysis,
            line_as_of,
            replay_mode,
            sources_unavailable,
            sonnet_model,
            prompt_version,
            now,
        )

    if pg is not None:
        await pg.execute(
            "INSERT INTO research_reports "
            "(query_id, report, line_as_of, replay_mode, model_version) "
            "VALUES ($1, $2, $3, $4, $5)",
            report.query_id,
            report.model_dump_json(),
            report.line_as_of,
            report.replay_mode,
            report.model_version,
        )

    return report
