"""Shared normalization utilities (DESIGN.md §5 Phase 0).

"SHA-256 the normalized record for content_hash." / "No retention of raw HTML once
normalized text is extracted." These are used by any FeedClient implementation that
builds contract records from raw source data. The replay FeedClient doesn't need
them — the fixture is already normalized (content_hash pre-computed by
scripts/author_fixture_v0.py) — but live implementations (M8) call these when
shaping raw nflverse/CFBD/scrape responses into StatRecord/SemanticDoc.
"""

import hashlib
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def content_hash(text: str) -> str:
    """SHA-256 of a normalized record's canonical text representation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_html(raw_html: str) -> str:
    """Strip HTML tags and collapse whitespace, leaving only normalized text.

    DESIGN.md is explicit that raw HTML must not be retained once text is
    extracted — this is the one place that conversion happens.
    """
    without_tags = _TAG_RE.sub(" ", raw_html)
    return _WHITESPACE_RE.sub(" ", without_tags).strip()
