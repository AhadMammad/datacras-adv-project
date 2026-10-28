"""End-to-end against the six PostgreSQL instances (scripts/verify.sh --keep). Skipped when unreachable.

WARNING: truncates every source table in the configured databases.
"""
from datetime import datetime, timedelta, timezone

import pytest

from advsim import backfill, validate
from advsim.schema import Schema
from advsim.sink.postgres import PgSink
from advsim.stream.engine import Engine

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def sink(settings, schema):
    s = PgSink(schema, settings.urls)
    down = {db: msg for db, msg in s.ping().items() if msg != "ok"}
    if down:
        pytest.skip(f"databases not reachable: {down}")
    yield s
    s.close()


def test_backfill_validate_and_stream(settings, schema, sink, capsys):
    end = datetime.now(timezone.utc)
    start = (end - timedelta(days=21)).date()
    w = backfill.build_world(settings, schema, start, end, seed=11)
    sink.reset()
    backfill.load_world(w, sink)
    assert backfill.load_events(w, sink, start, end) > 0
    assert validate.run(schema, sink)

    engine = Engine(settings, Schema(), PgSink(schema, settings.urls), speed=5000, seed=3)
    engine.run(duration=20)
    assert engine.stats["impression_event"] > 0
    assert engine.stats["updates"] > 0
    assert validate.run(schema, sink, orphan_tolerance=0.01)
