"""Single source of truth for every runtime tunable (DESIGN.md §7, §9, §11, PLAN.md Config)."""

from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class EloConfig(BaseModel):
    k: float = 20.0
    home_field: float = 65.0
    mov_multiplier: float = 1.0


class EdgeConfig(BaseModel):
    logistic_scale: float = 400.0  # Elo-diff -> probability logistic divisor
    ev_value_threshold_pct: float = 3.0
    ev_no_value_threshold_pct: float = -3.0


class CacheConfig(BaseModel):
    cosine_threshold: float = 0.92


class TtlConfig(BaseModel):
    odds_minutes_live: int = 5
    odds_minutes_replay: int = 60
    injuries_minutes: int = 30
    weather_hours: int = 3
    recaps_days: int = 7


class DecayConfig(BaseModel):
    half_life_hours_live_odds: float = 0.5
    half_life_hours_injury: float = 24.0
    half_life_hours_weather: float = 12.0
    half_life_hours_stats: float = 24.0 * 90
    half_life_hours_recap: float = 24.0 * 3


class RetrievalConfig(BaseModel):
    k_stats: int = 20
    k_semantic: int = 10
    k_live: int = 10
    timeout_seconds_per_source: float = 2.5
    context_budget_chunks: int = 40


class CostConfig(BaseModel):
    per_query_usd_cap: float = 0.15
    per_query_usd_alert: float = 0.10
    per_day_usd_cap: float = 2.0
    per_day_usd_alert_pct: float = 0.80


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Replay / fixture mode
    replay_mode: bool = True
    replay_llm: bool = True
    fixture_name: str = "synthetic_v0"

    # Responsible-gaming chokepoint
    gating_enabled: bool = False

    # Feature guards
    odds_api_enabled: bool = False

    # Service connections (host defaults; compose overrides via env)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "hailmary"
    postgres_password: str = "hailmary"
    postgres_db: str = "hailmary"

    elasticsearch_host: str = "http://localhost:9200"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Secrets (local .env only; unset in CI)
    anthropic_api_key: str | None = None
    voyage_api_key: str | None = None
    cfbd_api_key: str | None = None
    odds_api_key: str | None = None

    # Prompt/model versioning
    prompt_version: str = "v1"
    haiku_model: str = "claude-haiku-4-5"
    sonnet_model: str = "claude-sonnet-4-6"
    voyage_model: str = "voyage-3"
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Nested tunable groups
    elo: EloConfig = EloConfig()
    edge: EdgeConfig = EdgeConfig()
    cache: CacheConfig = CacheConfig()
    ttl: TtlConfig = TtlConfig()
    decay: DecayConfig = DecayConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    cost: CostConfig = CostConfig()

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
