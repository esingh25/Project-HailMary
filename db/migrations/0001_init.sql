-- DESIGN.md §6.4 — system-of-record DDL. Transcribed verbatim.

CREATE TABLE research_queries (
  query_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL,
  session_id    UUID NOT NULL,
  raw_text      TEXT NOT NULL,
  sport         TEXT NOT NULL,
  received_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE retrieval_plans (
  query_id       UUID PRIMARY KEY REFERENCES research_queries(query_id),
  intent         TEXT NOT NULL,
  entities       JSONB NOT NULL,
  conditions     JSONB NOT NULL,
  target_indexes TEXT[] NOT NULL,
  prompt_version TEXT NOT NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE research_reports (
  query_id      UUID PRIMARY KEY REFERENCES research_queries(query_id),
  report        JSONB NOT NULL,          -- serialized ResearchReport
  line_as_of    TIMESTAMP NOT NULL,
  replay_mode   BOOLEAN NOT NULL DEFAULT FALSE,
  model_version TEXT NOT NULL,
  generated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE team_ratings (
  team_id     TEXT NOT NULL,
  sport       TEXT NOT NULL,
  season      INT NOT NULL,
  rating      REAL NOT NULL,
  as_of       TIMESTAMP NOT NULL,
  -- sport is part of the key (not just team_id, season): team abbreviations can
  -- collide across NFL/CFB (e.g. "MIA"), and DESIGN.md's own TeamRating contract
  -- (§4) already carries sport as a field — the original §6.4 DDL omitted it from
  -- the key, which this corrects before the nightly Elo job (M2) writes to it.
  PRIMARY KEY (team_id, sport, season)
);

CREATE TABLE semantic_cache_index (
  cache_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  placeholder_text TEXT NOT NULL,        -- query with [TEAM]/[PLAYER] placeholders
  qdrant_point_id  UUID NOT NULL,        -- vector lives in Qdrant
  merged_context  JSONB NOT NULL,        -- reusable MergedContext (sans live odds)
  prompt_version  TEXT NOT NULL,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  last_hit_at     TIMESTAMP
);

CREATE TABLE odds_archive (
  id           BIGSERIAL PRIMARY KEY,
  game_id      TEXT NOT NULL,
  book         TEXT NOT NULL,
  market       TEXT NOT NULL,
  selection    TEXT NOT NULL,
  line         REAL,
  price        INT NOT NULL,
  captured_at  TIMESTAMP NOT NULL
);
CREATE INDEX idx_odds_archive_game ON odds_archive (game_id, captured_at DESC);

CREATE TABLE api_budget (
  source       TEXT PRIMARY KEY,        -- e.g. 'the_odds_api'
  period_start DATE NOT NULL,
  calls_used   INT NOT NULL DEFAULT 0,
  calls_limit  INT NOT NULL             -- 500 for The Odds API free tier
);

CREATE TABLE ingestion_log (
  id           BIGSERIAL PRIMARY KEY,
  source       TEXT NOT NULL,
  records      INT NOT NULL,
  status       TEXT NOT NULL,           -- ok | partial | failed
  ran_at       TIMESTAMP NOT NULL DEFAULT NOW(),
  detail       JSONB
);

CREATE TABLE events (
  id           BIGSERIAL PRIMARY KEY,
  query_id     UUID,
  phase        TEXT NOT NULL,
  event        TEXT NOT NULL,           -- plan_built | fanout_done | cache_hit | ...
  detail       JSONB,
  ts           TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_events_query ON events (query_id, ts);

CREATE TABLE session_turns (
  id                BIGSERIAL PRIMARY KEY,
  session_id        UUID NOT NULL,
  user_id           UUID NOT NULL,
  direction         TEXT NOT NULL,
  text              TEXT NOT NULL,
  query_id          UUID,
  resolved_entities JSONB,
  ts                TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_session_turns ON session_turns (session_id, ts);
