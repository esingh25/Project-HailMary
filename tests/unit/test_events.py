"""Unit tests for the events/ingestion_log writers and JSON logging config."""

import json
import logging

import pytest

from hailmary.obs.events import record_event, record_ingestion
from hailmary.obs.logging_config import JsonFormatter, configure_logging


class FakePG:
    def __init__(self):
        self.calls: list[tuple] = []

    async def execute(self, query, *args):
        self.calls.append((query, args))


@pytest.mark.unit
async def test_record_event_writes_expected_columns():
    pg = FakePG()
    await record_event(
        pg, phase="decompose", event="plan_built", query_id="q1", detail={"intent": "spread"}
    )

    query, args = pg.calls[0]
    assert "INSERT INTO events" in query
    assert args[0] == "q1"
    assert args[1] == "decompose"
    assert args[2] == "plan_built"
    assert json.loads(args[3]) == {"intent": "spread"}


@pytest.mark.unit
async def test_record_event_allows_none_detail_and_query_id():
    pg = FakePG()
    await record_event(pg, phase="ingestion", event="worker_started")
    query, args = pg.calls[0]
    assert args[0] is None
    assert args[3] is None


@pytest.mark.unit
async def test_record_ingestion_writes_expected_columns():
    pg = FakePG()
    await record_ingestion(pg, source="nflverse", records=42, status="ok")
    query, args = pg.calls[0]
    assert "INSERT INTO ingestion_log" in query
    assert args == ("nflverse", 42, "ok", args[3], None)


@pytest.mark.unit
async def test_record_ingestion_rejects_unknown_status():
    pg = FakePG()
    with pytest.raises(ValueError):
        await record_ingestion(pg, source="nflverse", records=0, status="bogus")


@pytest.mark.unit
def test_json_formatter_produces_valid_json():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"


@pytest.mark.unit
def test_configure_logging_sets_a_single_json_handler():
    configure_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
