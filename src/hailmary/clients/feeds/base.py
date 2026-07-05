"""FeedClient protocol — the replay seam (DESIGN.md §5 Phase 0, §9 failure modes).

Live and replay implementations are interchangeable behind this protocol; no phase
code checks REPLAY_MODE directly except the factory that picks which implementation
to construct. Methods return the same Phase 0 contract/internal types regardless of
whether the data came from a live feed or the fixture — a live implementation is
responsible for shaping raw feed responses into these same types (built in M8).
"""

from typing import Protocol

from hailmary.schemas.contracts import InjuryRecord, OddsSnapshot, SemanticDoc, StatRecord
from hailmary.schemas.internal import EntityMap, WeatherRecord


class FeedClient(Protocol):
    async def get_stats(self, sport: str) -> list[StatRecord]: ...

    async def get_semantic_docs(self, sport: str) -> list[SemanticDoc]: ...

    async def get_odds(self, game_id: str) -> list[OddsSnapshot]: ...

    async def get_injuries(self, team_id: str) -> list[InjuryRecord]: ...

    async def get_weather(self, game_id: str) -> list[WeatherRecord]: ...

    async def get_entity_map(self) -> EntityMap: ...
