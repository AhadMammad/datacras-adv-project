"""advsim command line.

  advsim backfill --profile small [--start 2026-01-01] [--end now] [--seed 42] [--reset] [--workers N]
  advsim run      --profile small [--speed 1] [--duration 2h]
  advsim reset    [--db crm_db ...]
  advsim validate [--orphan-tolerance 0.0]
  advsim stats
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date, datetime, timezone

import yaml

from .config import load_settings
from .schema import Schema
from .sink.postgres import PgSink


def parse_duration(s: str | None) -> float | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", s.strip())
    if not m:
        raise argparse.ArgumentTypeError(f"bad duration {s!r} (use e.g. 90s, 30m, 2h, 1d)")
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def parse_dq(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        out[k.strip()] = yaml.safe_load(v)
    return out


def parse_end(s: str) -> datetime:
    if s == "now":
        return datetime.now(timezone.utc)
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def require_dbs(sink: PgSink) -> None:
    bad = {db: msg for db, msg in sink.ping().items() if msg != "ok"}
    if bad:
        for db, msg in bad.items():
            print(f"cannot reach {db}: {msg}", file=sys.stderr)
        sys.exit("start the databases first: scripts/verify.sh --keep (or docker compose up -d + deploy DDL)")


def cmd_backfill(a) -> None:
    from . import backfill
    settings = load_settings(a.profile, parse_dq(a.dq))
    schema = Schema()
    start = date.fromisoformat(a.start or str(settings.profile.get("start")))
    end = parse_end(a.end)
    seed = a.seed if a.seed is not None else int(settings.profile.get("seed", 42))
    sink = PgSink(schema, settings.urls)
    if not a.dry_run:
        require_dbs(sink)
    w = backfill.build_world(settings, schema, start, end, seed)
    if a.dry_run:
        print("dry run: nothing written")
        return
    try:
        if a.reset:
            sink.reset()
            backfill.log("reset: all source tables truncated")
        backfill.load_world(w, sink)
        t0 = time.time()
        n = backfill.load_events(w, sink, start, end, a.workers)
        backfill.log(f"events: {n:,} rows in {time.time() - t0:.0f}s")
    finally:
        sink.close()


def cmd_run(a) -> None:
    from .stream.engine import Engine
    settings = load_settings(a.profile, parse_dq(a.dq))
    schema = Schema()
    sink = PgSink(schema, settings.urls)
    require_dbs(sink)
    seed = a.seed if a.seed is not None else int(time.time())
    Engine(settings, schema, sink, a.speed, seed).run(parse_duration(a.duration))


def cmd_reset(a) -> None:
    settings = load_settings("small")
    sink = PgSink(Schema(), settings.urls)
    require_dbs(sink)
    sink.reset(a.db or None)
    sink.close()
    print("truncated:", ", ".join(a.db or settings.urls))


def cmd_validate(a) -> None:
    from . import validate
    settings = load_settings("small")
    schema = Schema()
    sink = PgSink(schema, settings.urls)
    require_dbs(sink)
    ok = validate.run(schema, sink, a.orphan_tolerance)
    sink.close()
    sys.exit(0 if ok else 1)


def cmd_stats(a) -> None:
    settings = load_settings("small")
    schema = Schema()
    sink = PgSink(schema, settings.urls)
    require_dbs(sink)
    grand = 0
    for db in schema.systems:
        counts = sink.counts(db)
        total = sum(counts.values())
        grand += total
        print(f"== {db}: {total:,} rows")
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"   {name:45s} {n:>12,}")
    print(f"== total: {grand:,} rows")
    sink.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="advsim", description="Realistic fake data for the six advertising source databases.")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("backfill", help="generate history from --start to --end and load it")
    b.add_argument("--profile", default="small")
    b.add_argument("--start", help="first day (default: profile start, 2026-01-01)")
    b.add_argument("--end", default="now", help="ISO timestamp or 'now'")
    b.add_argument("--seed", type=int)
    b.add_argument("--reset", action="store_true", help="truncate all source tables first")
    b.add_argument("--workers", type=int, default=1, help="parallel processes for event loading")
    b.add_argument("--dq", action="append", metavar="KEY=VALUE", help="data-quality noise, e.g. --dq late_events=0.02")
    b.add_argument("--dry-run", action="store_true", help="build in memory only")
    b.set_defaults(func=cmd_backfill)

    r = sub.add_parser("run", help="continuous simulation from now on (Ctrl-C to stop)")
    r.add_argument("--profile", default="small")
    r.add_argument("--speed", type=float, default=1.0, help="activity multiplier; timestamps stay wall-clock")
    r.add_argument("--duration", help="stop after e.g. 30m, 2h (default: run until stopped)")
    r.add_argument("--seed", type=int)
    r.add_argument("--dq", action="append", metavar="KEY=VALUE")
    r.set_defaults(func=cmd_run)

    x = sub.add_parser("reset", help="truncate source tables (ref code sets are kept)")
    x.add_argument("--db", action="append", help="limit to these databases")
    x.set_defaults(func=cmd_reset)

    v = sub.add_parser("validate", help="check cross-database references and business invariants")
    v.add_argument("--orphan-tolerance", type=float, default=0.0, help="allowed share of dangling soft references")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("stats", help="row counts per database and table")
    s.set_defaults(func=cmd_stats)

    a = p.parse_args()
    a.func(a)
