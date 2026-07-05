"""Replay FeedClient — serves fixtures/<name>/ data, filtered by the virtual clock.

DESIGN.md §5 Phase 0: "With REPLAY_MODE=true, all feed clients read from the fixture
and the system clock used for freshness math is a virtual clock pinned inside the
fixture week." Only data whose own timestamp is <= the virtual clock is returned —
a live feed could never hand back a snapshot captured in the future.
"""

import json
from datetime import datetime
from pathlib import Path

from hailmary.schemas.contracts import InjuryRecord, OddsSnapshot, SemanticDoc, StatRecord
from hailmary.schemas.internal import EntityMap, WeatherRecord

FIXTURES_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "fixtures"


class FixtureData:
    """Parses one fixtures/<name>/ directory into typed in-memory records."""

    def __init__(self, fixture_name: str):
        self.dir = FIXTURES_ROOT / fixture_name
        if not self.dir.is_dir():
            raise FileNotFoundError(f"No fixture directory at {self.dir}")

        self.manifest: dict = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        self.virtual_clock: datetime = datetime.fromisoformat(self.manifest["virtual_clock"])

        self.stats = [StatRecord.model_validate(r) for r in self._read_jsonl("stats.jsonl")]
        self.semantic_docs = [
            SemanticDoc.model_validate(r) for r in self._read_jsonl("semantic_docs.jsonl")
        ]
        self.odds = [
            OddsSnapshot.model_validate(r) for r in self._read_jsonl("odds_timeseries.jsonl")
        ]
        self.injuries = [InjuryRecord.model_validate(r) for r in self._read_jsonl("injuries.jsonl")]
        self.weather = [WeatherRecord.model_validate(r) for r in self._read_jsonl("weather.jsonl")]
        self.entity_map = EntityMap.model_validate(
            json.loads((self.dir / "entity_map.json").read_text(encoding="utf-8"))
        )
        self.embeddings: dict = json.loads(
            (self.dir / "embeddings.json").read_text(encoding="utf-8")
        )

    def _read_jsonl(self, name: str) -> list[dict]:
        path = self.dir / name
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


class ReplayFeedClient:
    """FeedClient implementation backed by a loaded fixture (DESIGN.md §5 Phase 0)."""

    def __init__(self, fixture: FixtureData):
        self._fixture = fixture

    @property
    def now(self) -> datetime:
        return self._fixture.virtual_clock

    async def get_stats(self, sport: str) -> list[StatRecord]:
        return [s for s in self._fixture.stats if s.sport == sport and s.indexed_at <= self.now]

    async def get_semantic_docs(self, sport: str) -> list[SemanticDoc]:
        return [
            d
            for d in self._fixture.semantic_docs
            if d.sport == sport and d.published_at <= self.now
        ]

    async def get_odds(self, game_id: str) -> list[OddsSnapshot]:
        return [o for o in self._fixture.odds if o.game_id == game_id and o.captured_at <= self.now]

    async def get_injuries(self, team_id: str) -> list[InjuryRecord]:
        return [
            i for i in self._fixture.injuries if i.team_id == team_id and i.report_date <= self.now
        ]

    async def get_weather(self, game_id: str) -> list[WeatherRecord]:
        return [
            w for w in self._fixture.weather if w.game_id == game_id and w.captured_at <= self.now
        ]

    async def get_entity_map(self) -> EntityMap:
        return self._fixture.entity_map
