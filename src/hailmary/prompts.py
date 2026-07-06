"""Centralized prompt-version stamp (DESIGN.md §4: RetrievalPlan/ResearchReport
`prompt_version` field — used for cache keying, stale-plan detection, and
semantic-cache invalidation on a prompt change, per §11 retention policy).

Bump this whenever a guardrail/extraction/synthesis prompt changes meaning —
that invalidates the semantic cache and, in replay mode, any recorded cassette.
"""

PROMPT_VERSION = "v1"
