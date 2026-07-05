"""Clock abstraction so freshness/decay logic is testable and replay-mode-aware.

DESIGN.md §5 Phase 0: "In replay mode, 'now' is the fixture's virtual clock, so
freshness logic still exercises end-to-end."
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class VirtualClock:
    """Pinned to a fixture's virtual_clock timestamp for deterministic replay."""

    pinned: datetime

    def now(self) -> datetime:
        return self.pinned
