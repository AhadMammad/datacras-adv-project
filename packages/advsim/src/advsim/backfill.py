"""Historical backfill: build the world in memory, load it table by table, then stream events day by day."""
from __future__ import annotations

import multiprocessing as mp
import time
from datetime import date, datetime, timedelta

from psycopg import sql

from . import dq
from .config import Settings
from .rng import Rand
from .scenarios import audiences, campaigns, clients, delivery, finance, org, supply
from .schema import Schema
from .sink.postgres import PgSink
from .world import World

EVENT_TABLES = ("impression_event", "click_event", "conversion_event", "video_completion_event",
                "viewability_measurement", "delivery_pacing")


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def build_world(settings: Settings, schema: Schema, start: date, end: datetime, seed: int) -> World:
    w = World(settings, schema, start, end.date(), seed)
    w.now = end
    t0 = time.time()
    for name, step in (("org", org.build), ("supply", supply.build), ("audiences", audiences.build),
                       ("clients", clients.build), ("campaigns", campaigns.build)):
        step(w)
        log(f"built {name}: {sum(len(v) for v in w.reg.rows.values()):,} rows so far")
    delivery.plan(w, end)
    finance.build(w)
    generic_tables(w)
    n = w.fill.resolve_pending(w.rnd)
    dq.degrade_rows(w.reg.rows, schema, w.lc, w.dq, w.rnd.child("dq"))
    log(f"world ready: {len(w.advertisers)} advertisers, {len(w.campaigns)} campaigns, "
        f"{sum(len(c.line_items) for c in w.campaigns)} line items, {sum(len(v) for v in w.reg.rows.values()):,} rows "
        f"({n:,} late-bound references) in {time.time() - t0:.1f}s")
    return w


def generic_tables(w: World) -> None:
    """Any table no scenario wrote gets a handful of rows tied to random advertisers/campaigns."""
    rnd = w.rnd.child("generic")
    n = int(w.cfg.get_path("generic.rows_per_table", 25))
    for name in w.s.tables:
        if w.reg.count(name) or name in EVENT_TABLES:
            continue
        for _ in range(n):
            camp = rnd.choice(w.campaigns) if w.campaigns else None
            if camp:
                ctx = w.adv_ctx(camp.adv, rnd.date_between(camp.start - timedelta(days=20), min(camp.end, w.today)),
                                entities={"campaign": camp.id, "brand": camp.brand["brand_id"]}, scale=camp.budget / 4)
            else:
                ctx = w.ctx(rnd.date_between(w.start, w.today))
            w.make(name, {}, ctx, rnd)
        log(f"generic rows for {name}: {n}")


def load_world(w: World, sink: PgSink) -> None:
    for db in w.s.systems:
        order, deferred = w.s.load_plan(db)
        assert not deferred, deferred
        total = 0
        for table in order:
            total += sink.copy_dicts(table, w.reg.rows.get(table, []))
        sink.commit(db)
        log(f"loaded {db}: {total:,} rows")


def ensure_partitions(sink: PgSink, schema: Schema, first: date, last: date) -> None:
    months = (last.year - first.year) * 12 + last.month - first.month + 2
    db = "adserver_db"
    for t in schema.systems[db].tables:
        if t.partition_key:
            sink.execute(db, sql.SQL("SELECT util.ensure_monthly_partitions({}::regclass, {}, {})").format(
                sql.Literal(t.fqn), sql.Literal(first.replace(day=1)), sql.Literal(months)))
    sink.commit(db)


def load_events(w: World, sink: PgSink, start: date, end: datetime, workers: int = 1) -> int:
    days = [start + timedelta(days=i) for i in range((end.date() - start).days + 1)]
    ensure_partitions(sink, w.s, start, end.date())
    if workers <= 1:
        return sum(event_days(w, sink, days, end))
    sink.close()
    global _WORLD
    _WORLD = w
    chunks = [days[i::workers] for i in range(workers)]
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        totals = pool.starmap(_worker, [(chunk, end, sink.urls) for chunk in chunks])
    return sum(totals)


_WORLD: World | None = None


def _worker(days: list[date], end: datetime, urls: dict) -> int:
    sink = PgSink(_WORLD.s, urls)
    try:
        return sum(event_days(_WORLD, sink, days, end))
    finally:
        sink.close()


def event_days(w: World, sink: PgSink, days: list[date], end: datetime):
    t0 = time.time()
    for i, d in enumerate(days):
        writer = delivery.EventWriter(w, Rand(w.seed, f"events-{d.isoformat()}"))
        out = writer.day(d, delivery.active_on(w, d), until=end)
        n = 0
        for table in EVENT_TABLES:
            n += sink.copy_dicts(table, out[table])
        sink.commit("adserver_db")
        if i % 14 == 0 or i == len(days) - 1:
            log(f"events {d}: {n:,} rows ({time.time() - t0:.0f}s elapsed)")
        yield n
