"""Smoke-test SQL: inserts one valid row per table, then asserts behaviour. Runs in a rolled-back transaction."""
from __future__ import annotations

import re
import re._constants as C
import re._parser as P
from graphlib import TopologicalSorter
from pathlib import Path

from .emit_sql import lit
from .model import Column, Model, System, Table

SMOKE_TS = "2026-10-15 12:00:00+00"
SMOKE_PARTITION_SUFFIX = "_p202610"


def regex_sample(pattern: str) -> str:
    """Shortest string matching a (simple) regex, built from Python's regex parser."""
    def pick_in(items) -> str:
        if items and items[0][0] is C.NEGATE:
            banned = {chr(v) for op, v in items[1:] if op is C.LITERAL}
            return next(ch for ch in "aA0x" if ch not in banned)
        op, av = items[0]
        if op is C.LITERAL:
            return chr(av)
        if op is C.RANGE:
            return chr(av[0])
        if op is C.CATEGORY:
            return {C.CATEGORY_DIGIT: "1", C.CATEGORY_SPACE: " "}.get(av, "a")
        raise ValueError(f"unsupported class in {pattern!r}")

    def gen(items) -> str:
        out = ""
        for op, av in items:
            if op is C.LITERAL:
                out += chr(av)
            elif op is C.ANY:
                out += "a"
            elif op is C.IN:
                out += pick_in(av)
            elif op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT):
                lo, _, sub = av
                out += gen(sub) * lo
            elif op is C.SUBPATTERN:
                out += gen(av[-1])
            elif op is C.BRANCH:
                out += gen(av[1][0])
            elif op is C.CATEGORY:
                out += "1" if av is C.CATEGORY_DIGIT else "a"
            elif op is C.AT:
                continue
            else:
                raise ValueError(f"unsupported regex op {op} in {pattern!r}")
        return out

    s = gen(P.parse(pattern))
    if not re.search(pattern, s):
        raise ValueError(f"sample {s!r} does not match {pattern!r}")
    return s


def value_for(t: Table, c: Column) -> str:
    if c.code_set:
        return f"(SELECT code FROM ref.{c.code_set} ORDER BY sort_order LIMIT 1)"
    if c.ref:
        if c.ref.enforced:
            return f"(SELECT {c.ref.target_column} FROM {c.ref.target_fqn} LIMIT 1)"
        return "uuidv7()"
    for ch in c.checks:
        if ch.kind == "in":
            return lit(ch.values[0])
        if ch.kind == "regex":
            return lit(regex_sample(ch.pattern))
    t_ = c.pg_type
    if t_ == "text":
        return lit(f"smoke {t.name}.{c.name}")
    if t_ == "char(3)":
        return lit("USD")
    if t_.startswith(("numeric", "integer", "bigint")):
        return "1"
    if t_ == "date":
        return lit(SMOKE_TS[:10])
    if t_ == "timestamptz":
        return lit(SMOKE_TS)
    if t_ == "boolean":
        return "false"
    raise ValueError(f"no smoke value for {t.key}.{c.name} ({t_})")


def insert_order(s: System) -> list[Table]:
    by_fqn = {t.fqn: t for t in s.tables}
    graph = {t.fqn: {c.ref.target_fqn for c in t.columns
                     if c.ref and c.ref.enforced and not c.nullable and c.ref.target_fqn != t.fqn}
             for t in s.tables}
    return [by_fqn[f] for f in TopologicalSorter(graph).static_order()]


def emit_system(s: System) -> str:
    out = [f"-- Generated smoke test for {s.database}. Runs in one transaction and rolls back.\n",
           "\\set ON_ERROR_STOP on\nBEGIN;\n\n"]
    for t in insert_order(s):
        cols = [c for c in t.columns if not c.nullable and c.default is None]
        names = ", ".join(c.name for c in cols)
        vals = ", ".join(value_for(t, c) for c in cols)
        out.append(f"INSERT INTO {t.fqn} ({names})\nVALUES ({vals});\n")

    checks = " OR ".join(f"(SELECT count(*) FROM {t.fqn}) <> 1" for t in s.tables)
    out.append(f"\nDO $$ BEGIN\n    IF {checks} THEN\n"
               f"        RAISE EXCEPTION 'smoke: expected exactly one row per table';\n    END IF;\nEND $$;\n")

    first = s.tables[0]
    out.append(f"\n-- audit trigger: updated_* maintained, created_* immutable\n"
               f"SET LOCAL app.actor = 'smoke_user';\n"
               f"UPDATE {first.fqn} SET created_by = 'tamper', updated_by = 'tamper';\n"
               f"DO $$ BEGIN\n    IF NOT EXISTS (SELECT 1 FROM {first.fqn}\n"
               f"                   WHERE updated_at > created_at AND updated_by = 'smoke_user' AND created_by <> 'tamper') THEN\n"
               f"        RAISE EXCEPTION 'smoke: audit trigger failed on {first.fqn}';\n    END IF;\nEND $$;\n")

    coded = next(((t, c) for t in s.tables for c in t.columns if c.code_set), None)
    if coded:
        t, c = coded
        out.append(negative(f"UPDATE {t.fqn} SET {c.name} = '__invalid__'", "foreign_key_violation",
                            f"code set FK on {t.fqn}.{c.name}"))
    listed = next(((t, c) for t in s.tables for c in t.columns
                   if any(ch.kind == "in" for ch in c.checks)), None)
    if listed:
        t, c = listed
        out.append(negative(f"UPDATE {t.fqn} SET {c.name} = '__invalid__'", "check_violation",
                            f"CHECK on {t.fqn}.{c.name}"))

    for t in s.tables:
        if t.partition_key:
            out.append(f"\nDO $$ BEGIN\n    IF (SELECT tableoid::regclass::text FROM {t.fqn}) <> '{t.fqn}{SMOKE_PARTITION_SUFFIX}' THEN\n"
                       f"        RAISE EXCEPTION 'smoke: {t.fqn} row not routed to monthly partition';\n    END IF;\nEND $$;\n")
    out.append("\nROLLBACK;\n")
    return "".join(out)


def negative(stmt: str, condition: str, label: str) -> str:
    return (f"\n-- expect {condition}: {label}\n"
            f"DO $$ BEGIN\n    {stmt};\n    RAISE EXCEPTION 'smoke: {label} not enforced';\n"
            f"EXCEPTION WHEN {condition} THEN NULL;\nEND $$;\n")


def emit(model: Model, root: Path) -> None:
    out = root / "tests" / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    for s in model.systems.values():
        (out / f"{s.database}.sql").write_text(emit_system(s))
