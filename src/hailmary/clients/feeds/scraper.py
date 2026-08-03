"""Curated-source scraper for prose docs (DESIGN.md §5 Phase 0).

Fetches a small allowlisted set of recap/analysis pages, strips them to text
(normalize.strip_html — no raw HTML retained, per §7), and shapes SemanticDoc
rows keyed by content hash. The source list is deliberately config-owned and
tiny: this is a curated feed, not a crawler.

"The list is curated" is a convention, not a control, so it is not relied on:
every URL is checked for an http(s) scheme and a non-internal host before the
request, the post-redirect URL is checked again, and the body is read with a
hard byte cap. Without those, a single edited config row (or a redirect from an
otherwise-legitimate page) turns this into an SSRF primitive against anything
the host can reach — cloud metadata endpoints included — and an oversized body
is unbounded memory during ingestion.
"""

import ipaddress
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from hailmary.ingestion.normalize import content_hash, strip_html
from hailmary.schemas.contracts import SemanticDoc

MAX_DOC_CHARS = 8000
# Generous next to MAX_DOC_CHARS (which truncates *after* stripping markup) but
# small enough that a hostile or misconfigured source cannot exhaust memory.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
ALLOWED_SCHEMES = frozenset({"http", "https"})
BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal"})


class UnsafeSourceURLError(ValueError):
    """Raised for a source URL that must not be fetched."""


def assert_safe_url(url: str) -> None:
    """Reject non-http(s) schemes and hosts that resolve to internal address space.

    An IP literal is checked directly. A hostname cannot be judged without
    resolving it, which this deliberately does not do — resolution here would
    be advisory anyway, since the address could change between the check and
    the request (DNS rebinding). The literal check plus the redirect re-check
    is defence in depth over the curated list, not a substitute for it.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeSourceURLError(f"Refusing non-http(s) source URL scheme: {parts.scheme!r}")

    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeSourceURLError(f"Source URL has no host: {url!r}")
    if host in BLOCKED_HOSTNAMES:
        raise UnsafeSourceURLError(f"Refusing internal host: {host!r}")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return  # a name, not a literal — nothing more we can check without resolving

    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local  # includes 169.254.169.254, the cloud metadata endpoint
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise UnsafeSourceURLError(f"Refusing non-public address: {host!r}")


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


async def _read_capped(response: httpx.Response) -> str | None:
    """Stream the body, abandoning it past MAX_RESPONSE_BYTES.

    A Content-Length check alone is not enough — it is absent on chunked
    responses and a hostile server can simply lie — so the running total is
    what actually enforces the cap.
    """
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
        return None

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


async def fetch_docs(sources: list[dict], client: httpx.AsyncClient) -> list[SemanticDoc]:
    """`sources` rows: {"url", "sport", "doc_type"} from config/curation."""
    docs = []
    fetched_at = datetime.now(UTC)
    for source in sources:
        url = source["url"]
        try:
            assert_safe_url(url)
        except UnsafeSourceURLError:
            continue  # a bad curation row is skipped, never fetched

        try:
            async with client.stream("GET", url, timeout=15.0, follow_redirects=True) as response:
                response.raise_for_status()
                # Redirects are followed, so the URL actually fetched may not be
                # the one that was vetted above. Re-check where we landed.
                assert_safe_url(str(response.url))
                raw_html = await _read_capped(response)
        except (httpx.HTTPError, UnsafeSourceURLError):
            continue  # one bad page never sinks the pass

        if raw_html is None:
            continue  # over the byte cap

        doc = doc_from_page(url, raw_html, source["sport"], source["doc_type"], fetched_at)
        if doc is not None:
            docs.append(doc)
    return docs
