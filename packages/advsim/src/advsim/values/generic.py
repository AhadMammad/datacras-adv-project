"""Schema-driven row builder: fills every column of any table with a valid, plausible value.

Scenarios pass the columns that carry business meaning (keys, names, money, dates, status);
`Filler.make` fills the rest from the column's type, CHECKs, code set and name, and keeps
references coherent through the row context (`Ctx.entities`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal

from advgen.model import Column, Table

from ..lifecycle import Lifecycles, phase_of
from ..registry import Registry
from ..rng import UTC, Rand
from ..schema import NON_CONTEXT_REF, Schema, numeric_bounds
from . import pools, semantic
from .regex import sample as regex_sample

EMAIL_HINT = re.compile(r"@")


@dataclass
class Ctx:
    """Row context: business date, money scale and the entities the row belongs to."""
    anchor: date
    today: date
    entities: dict = field(default_factory=dict)  # target table name -> id (None = leave empty)
    currency: str = "USD"
    scale: float = 50_000.0
    duration: int = 90
    label: str = ""
    domain: str = ""
    industry: str = ""
    people: tuple = ()
    geo: tuple = pools.US_GEO[0]

    def with_(self, **kw) -> "Ctx":
        ents = kw.pop("entities", None)
        c = replace(self, **kw)
        if ents is not None:
            c.entities = {**self.entities, **ents}
        return c

    def person(self, rnd: Rand) -> str:
        return rnd.choice(self.people) if self.people else rnd.fake.name()


def valid(c: Column, v) -> bool:
    """True if `v` satisfies the column's type bounds and CHECK constraints."""
    if v is None:
        return c.nullable
    if c.pg_type == "char(3)" and (not isinstance(v, str) or len(v) != 3):
        return False
    b = numeric_bounds(c.pg_type)
    if b and abs(float(v)) > b[0]:
        return False
    for ch in c.checks:
        if ch.kind == "in" and v not in ch.values:
            return False
        if ch.kind == "regex" and not re.search(ch.pattern, str(v)):
            return False
        if ch.kind == "range":
            if ch.min is not None and float(v) < ch.min:
                return False
            if ch.max is not None and float(v) > ch.max:
                return False
    return True


class Filler:
    def __init__(self, schema: Schema, reg: Registry, lifecycles: Lifecycles, rules: dict,
                 fill_optional: float = 0.8, fill_ref: float = 0.55) -> None:
        self.s = schema
        self.reg = reg
        self.lc = lifecycles
        self.rules = rules or {}
        self.fill_optional = fill_optional
        self.fill_ref = fill_ref
        self.pending: list[tuple[str, dict, Column]] = []  # refs to tables not generated yet
        self.uniques = {t.name: [tuple(u) for u in t.uniques] for t in schema.tables.values()}
        self.unique_cols = {t.name: {c for u in t.uniques for c in u} for t in schema.tables.values()}
        self.seq: dict[tuple[str, str], int] = {}
        self.live = False  # stream mode: new rows are created "now"

    # ------------------------------------------------------------ public
    def make(self, table: str, values: dict, ctx: Ctx, rnd: Rand, register: bool = True) -> dict:
        t = self.s.table(table)
        unknown = [k for k in values if not k.startswith("_") and not t.has(k)]
        if unknown:
            raise KeyError(f"{table}: unknown columns {unknown}")
        row = dict(values)
        created = row.pop("_created", None)
        if self.live:
            created = datetime.now(UTC)
        elif created is None:
            created = rnd.ts_on(min(ctx.anchor - timedelta(days=rnd.int(0, 10)), ctx.today))
            created = min(created, datetime.combine(ctx.today, datetime.min.time(), UTC) + timedelta(hours=23))
        pk = t.pk.name
        row.setdefault(pk, rnd.uuid7(created))
        for c in self.s.data_columns(table):
            if c.name in row:
                continue
            row[c.name] = self.value(t, c, row, ctx, rnd)
        self.fix_dates(t, row, values)
        self.fix_status(t, row, values, ctx, rnd)
        self.fix_uniques(t, row, values, ctx, rnd)
        actor = ctx.person(rnd)
        row.setdefault("created_at", created)
        row.setdefault("created_by", username(actor))
        if row.get("updated_at") is None:
            upd = created if self.live else created + timedelta(hours=rnd.int(0, 24 * 20))
            row["updated_at"] = min(upd, max(created, datetime.now(UTC)))
        row.setdefault("updated_by", row["created_by"] if rnd.chance(0.6) else username(ctx.person(rnd)))
        row.setdefault("_adv", ctx.entities.get("advertiser"))
        row.setdefault("_campaign", ctx.entities.get("campaign"))
        if register:
            self.reg.add(table, pk, row)
        return row

    def resolve_pending(self, rnd: Rand) -> int:
        """Fill references that pointed at tables generated later in the run."""
        done, left = 0, []
        for table, row, c in self.pending:
            target = self.reg.pick(c.ref.target_table, rnd, row)
            if target:
                row[c.name] = target[self.reg.pk[c.ref.target_table]]
                done += 1
            elif not c.nullable:
                left.append((table, row, c))
        self.pending = left
        if left:
            missing = sorted({f"{t}.{c.name}->{c.ref.target_table}" for t, _, c in left})
            raise RuntimeError(f"unresolvable required references: {missing}")
        return done

    # ------------------------------------------------------------ per column
    def value(self, t: Table, c: Column, row: dict, ctx: Ctx, rnd: Rand):
        rule = self.rules.get(f"{t.name}.{c.name}") or {}
        required = not c.nullable and c.default is None
        if c.ref:
            return self.ref_value(t, c, row, ctx, rnd, required)
        if c.pg_type == "boolean" and not c.nullable:
            return rnd.chance(rule.get("p_true", semantic.bool_prob(c.name)))
        if not required:
            p = rule.get("fill", self.fill_prob(c))
            if not rnd.chance(p):
                return None
        if "choices" in rule:
            return rnd.weighted(rule["choices"])
        if "const" in rule:
            return rule["const"]
        return self.scalar(t, c, ctx, rnd)

    def fill_prob(self, c: Column) -> float:
        n = c.name
        if semantic.has(n, r"(churn|discontinu|termination|dispute|rejection|cancel|credit_note|revision_reason|"
                           r"error|unmeasurable|closure|rejected|reversal|superseded|override|exclusion|"
                           r"mandatory|regulatory|remediation|incident|ivt_detection)"):
            return 0.06
        if semantic.has(n, r"(notes|comment|feedback)"):
            return 0.3
        if semantic.has(n, r"(currency|_name$|^title$|country)"):
            return 0.97
        return self.fill_optional

    def ref_value(self, t: Table, c: Column, row: dict, ctx: Ctx, rnd: Rand, required: bool):
        target = c.ref.target_table
        if target == t.name:
            return None
        if not NON_CONTEXT_REF.search(c.name) and target in ctx.entities:
            return ctx.entities[target]
        if not required and not rnd.chance(self.fill_ref):
            return None
        hit = self.reg.pick(target, rnd, {"_adv": ctx.entities.get("advertiser"),
                                          "_campaign": ctx.entities.get("campaign")})
        if hit:
            return hit[self.reg.pk[target]]
        self.pending.append((t.name, row, c))
        return None

    def scalar(self, t: Table, c: Column, ctx: Ctx, rnd: Rand):
        if c.code_set or any(ch.kind == "in" for ch in c.checks):
            return rnd.skewed(self.s.code_values(t.name, c.name))
        typ = c.pg_type
        if typ == "boolean":
            return rnd.chance(semantic.bool_prob(c.name))
        if typ == "char(3)":
            if semantic.has(c.name, "currency"):
                return ctx.currency
            if semantic.has(c.name, r"(country|jurisdiction)"):
                return rnd.weighted(pools.COUNTRIES3)
            return self.from_checks(c, rnd)
        if typ == "date":
            return self.date(c, ctx, rnd)
        if typ == "timestamptz":
            d = self.date(c, ctx, rnd)
            return None if d is None else semantic.as_ts(d, rnd)
        if typ == "uuid":
            return rnd.uuid7()
        b = numeric_bounds(typ)
        if b:
            return self.number(c, ctx, rnd, *b)
        v = semantic.text(c, t.name, ctx, rnd)
        if not valid(c, v):
            v = self.from_checks(c, rnd)
        return v

    def date(self, c: Column, ctx: Ctx, rnd: Rand):
        d = semantic.date_value(c.name, ctx, rnd)
        if d > ctx.today and semantic.PAST_ONLY.search(c.name):
            if c.nullable:
                return None
            d = ctx.today
        return d

    def number(self, c: Column, ctx: Ctx, rnd: Rand, maxv: float, digits: int):
        v = semantic.number(c, ctx, rnd, maxv, digits)
        lo, hi = -maxv, maxv
        for ch in c.checks:
            if ch.kind == "range":
                lo = max(lo, ch.min) if ch.min is not None else lo
                hi = min(hi, ch.max) if ch.max is not None else hi
        v = min(max(float(v), lo), hi)
        if digits == 0:
            return int(v)
        return Decimal(str(round(v, digits)))

    def from_checks(self, c: Column, rnd: Rand):
        for ch in c.checks:
            if ch.kind == "regex":
                return regex_sample(ch.pattern, rnd)
        if c.pg_type == "char(3)":
            return "USD"
        return semantic.words(c.name).capitalize()

    # ------------------------------------------------------------ row-level fixes
    def fix_dates(self, t: Table, row: dict, explicit: dict) -> None:
        for start, end in t.date_pairs:
            s, e = row.get(start), row.get(end)
            if s is not None and e is not None and e < s:
                if end in explicit and start not in explicit:
                    row[start] = e
                else:
                    row[end] = s

    def fix_status(self, t: Table, row: dict, explicit: dict, ctx: Ctx, rnd: Rand) -> None:
        col = self.s.status_col.get(t.name)
        if not col or col in explicit or t.name not in self.lc.machines:
            return
        start, end = (t.date_pairs[0] if t.date_pairs else (None, None))
        s = row.get(start) if start else ctx.anchor
        e = row.get(end) if end else None
        s, e = as_date(s), as_date(e)
        row[col] = self.lc.status(t.name, phase_of(s, e, ctx.today), rnd)

    def fix_uniques(self, t: Table, row: dict, explicit: dict, ctx: Ctx, rnd: Rand) -> None:
        for cols in self.uniques[t.name]:
            for attempt in range(60):
                key = tuple(row[c] for c in cols)
                if self.reg.claim(t.name, ",".join(cols), key):
                    break
                free = [c for c in cols if c not in explicit] or list(cols)
                for name in free:
                    row[name] = self.unique_value(t, t.col(name), ctx, rnd, attempt)
            else:
                raise RuntimeError(f"cannot find a unique value for {t.name}{cols}")

    def unique_value(self, t: Table, c: Column, ctx: Ctx, rnd: Rand, attempt: int):
        if any(ch.kind == "regex" for ch in c.checks):
            return self.from_checks(c, rnd)
        if c.pg_type != "text":
            return self.scalar(t, c, ctx, rnd)
        k = (t.name, c.name)
        self.seq[k] = self.seq.get(k, 0) + 1
        prefix = "".join(w[0] for w in t.name.split("_"))[:3].upper()
        return f"{prefix}-{ctx.anchor.year}-{self.seq[k]:06d}"


def as_date(v):
    if isinstance(v, datetime):
        return v.date()
    return v


def username(person: str) -> str:
    parts = person.lower().replace("'", "").split()
    return f"{parts[0][0]}.{parts[-1]}" if len(parts) > 1 else parts[0]
