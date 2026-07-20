"""Curated-source scraper for prose docs (DESIGN.md §5 Phase 0).

Fetches a small allowlisted set of recap/analysis pages, strips them to text
(normalize.strip_html — no raw HTML retained, per §7), and shapes SemanticDoc
rows keyed by content hash. The source list is deliberately config-owned and
tiny: this is a curated feed, not a crawler.
"""

from datetime import UTC, datetime

import httpx

from hailmary.ingestion.normalize import content_hash, strip_html
from hailmary.schemas.contracts import SemanticDoc

MAX_DOC_CHARS = 8000


def doc_from_page(
    url: str, raw_html: str, sport: str, doc_type: str, fetched_at: datetime
) -> SemanticDoc | None:
    text = strip_html(raw_html)[:MAX_DOC_CHARS].strip()
    if not text:
        return None
    digest = content_hash(text)
    return SemanticDoc(
        doc_id=f"scrape_{digest[:16]}",
        sport=sport,
        doc_type=doc_type,
        text=text,
        embedding_model="",  # stamped by the indexing step once embedded
        source=url,
        published_at=fetched_at,
        content_hash=digest,
    )


async def fetch_docs(sources: list[dict], client: httpx.AsyncClient) -> list[SemanticDoc]:
    """`sources` rows: {"url", "sport", "doc_type"} from config/curation."""
    docs = []
    fetched_at = datetime.now(UTC)
    for source in sources:
        try:
            response = await client.get(source["url"], timeout=15.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError:
            continue  # one bad page never sinks the pass; ingestion logs the count
        doc = doc_from_page(
            source["url"], response.text, source["sport"], source["doc_type"], fetched_at
        )
        if doc is not None:
            docs.append(doc)
    return docs
