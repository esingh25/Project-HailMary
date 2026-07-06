"""Stats sub-agent -> Elasticsearch (DESIGN.md §5 Phase 2).

"Translate entities + conditions into a structured ES query (filters on
team/player/week/season + conditions as range/term filters; BM25 over text_blob
for fuzzy phrasing)." A fixed query template, not an LLM loop — deterministic,
no relevance judgment beyond what ES itself scores.
"""

from datetime import datetime

from hailmary.clients.es import index_name_for_sport
from hailmary.schemas.contracts import Condition, QueryEntities, RetrievedChunk

_RANGE_OPERATORS = {"gt", "gte", "lt", "lte"}


def _condition_to_es_filter(condition: Condition) -> dict:
    field = f"fields.{condition.field}"
    if condition.operator in _RANGE_OPERATORS:
        return {"range": {field: {condition.operator: condition.value}}}
    if condition.operator == "eq":
        return {"term": {field: condition.value}}
    if condition.operator == "in":
        return {"terms": {field: condition.value}}
    if condition.operator == "between":
        lo, hi = condition.value
        return {"range": {field: {"gte": lo, "lte": hi}}}
    raise ValueError(f"Unsupported condition operator: {condition.operator!r}")


def build_stats_query(entities: QueryEntities, conditions: list[Condition], raw_text: str) -> dict:
    """Deterministic ES bool query — filters narrow to the matchup, BM25 handles
    fuzzy phrasing against text_blob."""
    filters: list[dict] = [{"term": {"season": entities.season}}]
    if entities.teams:
        filters.append({"terms": {"team_id": entities.teams}})
    if entities.players:
        filters.append({"terms": {"player_id": entities.players}})
    if entities.week is not None:
        filters.append({"term": {"week": entities.week}})
    filters.extend(_condition_to_es_filter(c) for c in conditions)

    query: dict = {"bool": {"filter": filters}}
    if raw_text:
        query["bool"]["must"] = [{"match": {"text_blob": raw_text}}]
    return query


def _hit_to_chunk(hit: dict, now: datetime) -> RetrievedChunk:
    source = hit["_source"]
    return RetrievedChunk(
        chunk_id=source["record_id"],
        source="stats_es",
        content=source["text_blob"],
        structured_data=source["fields"],
        index_score=hit.get("_score"),
        freshness_ts=datetime.fromisoformat(source["indexed_at"]),
        retrieved_at=now,
    )


async def fetch_stats(
    client,
    sport: str,
    entities: QueryEntities,
    conditions: list[Condition],
    raw_text: str,
    k: int,
    now: datetime,
) -> list[RetrievedChunk]:
    query = build_stats_query(entities, conditions, raw_text)
    response = await client.search(index=index_name_for_sport(sport), query=query, size=k)
    hits = response["hits"]["hits"]
    return [_hit_to_chunk(hit, now) for hit in hits]
