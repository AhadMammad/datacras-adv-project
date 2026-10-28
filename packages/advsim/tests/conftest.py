from datetime import date, datetime, timezone

import pytest

from advsim.backfill import build_world
from advsim.config import load_settings
from advsim.schema import Schema

END = datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)
START = date(2026, 3, 1)


@pytest.fixture(scope="session")
def schema():
    return Schema()


@pytest.fixture(scope="session")
def settings():
    return load_settings("tiny")


@pytest.fixture(scope="session")
def world(settings, schema):
    return build_world(settings, schema, START, END, seed=7)
