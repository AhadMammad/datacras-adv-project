"""Offline tests: every generated value satisfies the physical model, and runs are reproducible."""
from collections import Counter
from datetime import timedelta

from advsim.backfill import EVENT_TABLES, build_world
from advsim.lifecycle import Lifecycles
from advsim.rng import Rand
from advsim.scenarios import delivery
from advsim.values.generic import valid

from conftest import END, START


def invalid_values(schema, table, rows):
    bad = []
    for row in rows:
        for c in schema.table(table).columns:
            v = row.get(c.name)
            if c.is_audit:
                if v is None:
                    bad.append((table, c.name, v))
                continue
            if v is None and not c.nullable and c.default is not None:
                continue  # database default fills it (booleans default false)
            if not valid(c, v):
                bad.append((table, c.name, v))
            elif c.code_set and v is not None and v not in schema.code_values(table, c.name):
                bad.append((table, c.name, v))  # would violate the FK to ref.<code set>
    return bad


def test_every_table_is_generated(world, schema):
    empty = [t for t in schema.tables if t not in EVENT_TABLES and not world.reg.count(t)]
    assert not empty


def test_master_and_transaction_rows_satisfy_constraints(world, schema):
    bad = []
    for table, rows in world.reg.rows.items():
        bad += invalid_values(schema, table, rows)
    assert not bad, bad[:20]


def test_unique_keys_are_unique(world, schema):
    for t in schema.tables.values():
        for cols in t.uniques:
            keys = Counter(tuple(r[c] for c in cols) for r in world.reg.rows.get(t.name, []))
            dupes = [k for k, n in keys.items() if n > 1]
            assert not dupes, (t.name, cols, dupes[:3])


def test_enforced_references_resolve_within_the_database(world, schema):
    for t in schema.tables.values():
        for c in t.columns:
            if not (c.ref and c.ref.enforced):
                continue
            for r in world.reg.rows.get(t.name, []):
                v = r.get(c.name)
                if v is not None:
                    target = world.reg.get(v)
                    assert target is not None and target in world.reg.rows[c.ref.target_table], (t.name, c.name)


def test_soft_references_point_at_generated_rows(world, schema):
    for t in schema.tables.values():
        for c in t.columns:
            if c.ref and not c.ref.enforced and c.ref.target_table not in EVENT_TABLES:
                for r in world.reg.rows.get(t.name, []):
                    v = r.get(c.name)
                    assert v is None or world.reg.get(v) is not None, (t.name, c.name)


def test_date_pairs_are_ordered(world, schema):
    for t in schema.tables.values():
        for s, e in t.date_pairs:
            for r in world.reg.rows.get(t.name, []):
                if r.get(s) is not None and r.get(e) is not None:
                    assert r[e] >= r[s], (t.name, s, e)


def test_event_rows_satisfy_constraints(world, schema):
    rnd = Rand(1, "test-events")
    writer = delivery.EventWriter(world, rnd)
    writer.sample = 100  # dense enough that every event type shows up
    seen = Counter()
    d = START
    while d <= END.date():
        out = writer.day(d, delivery.active_on(world, d), until=END)
        for table, rows in out.items():
            seen[table] += len(rows)
            assert not invalid_values(schema, table, rows)[:5]
            ts_col = schema.table(table).partition_key
            assert all(r[ts_col] <= END + timedelta(days=1) for r in rows)
        d += timedelta(days=7)
    assert all(seen[t] > 0 for t in EVENT_TABLES), seen


def test_line_item_spend_respects_budget(world):
    for c in world.campaigns:
        for li in c.line_items:
            spend = sum(d.spend for d in li.daily.values())
            assert spend <= li.budget * 1.021


def test_same_seed_same_world(settings, schema, world):
    again = build_world(settings, schema, START, END, seed=7)
    assert [c.row["campaign_code"] for c in again.campaigns] == [c.row["campaign_code"] for c in world.campaigns]
    assert [round(c.budget, 2) for c in again.campaigns] == [round(c.budget, 2) for c in world.campaigns]


def test_load_plan_is_acyclic(schema):
    for db in schema.systems:
        order, deferred = schema.load_plan(db)
        assert len(order) == len(schema.systems[db].tables)
        assert not deferred


def test_lifecycles_cover_status_columns(schema, settings):
    lc = Lifecycles(schema, settings.lifecycles)
    assert len(lc.machines) >= 75
    for m in lc.machines.values():
        for phase in ("future", "current", "past"):
            assert set(m.phases[phase]) <= set(m.values)
