# DESIGN.md Amendments

DESIGN.md v1.0 is frozen; deviations are recorded here first ("doc changes
first"), never silently in code.

## A1 — LLM/embedding provider: Gemini instead of Anthropic + Voyage (2026-07-07)

**What the doc says:** §2/§5 name Anthropic (Claude Haiku for Phase 1 guardrail
+ extraction, Claude Sonnet for Phase 4 synthesis) and Voyage for embeddings.

**Deviation:** No Anthropic/Voyage keys were ever provisioned; the project's
live key will be Google Gemini. `clients/llm.py`'s live path now routes through
`instructor.from_provider` with provider-qualified model ids (e.g.
`HAIKU_MODEL=google/gemini-2.5-flash`, `SONNET_MODEL=google/gemini-2.5-pro`),
and `clients/voyage.py`'s live path embeds via the Gemini embeddings API
(e.g. `VOYAGE_MODEL=gemini-embedding-001`).

**What is unchanged:** the cassette layer (record once, replay keyless in CI),
prompt templates, contracts, and the two-call-site rule. Cassette keys include
the model string as-recorded, so the committed synthetic cassettes (bare
`claude-*` ids) replay unchanged until re-recorded.

**Follow-through when the Gemini key lands:** set `GEMINI_API_KEY` and
provider-qualified model ids in `.env`, re-record cassettes with
`scripts/record_cassettes.py`, and re-embed the document corpus with the same
embedding model before flipping semantic retrieval live (query and document
vectors must share one scheme).
