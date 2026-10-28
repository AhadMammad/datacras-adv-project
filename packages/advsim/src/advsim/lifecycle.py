"""Status lifecycles: which status a row has given its dates (backfill) and how it moves on (stream).

Every table with a lifecycle status column (overrides/table_rules.yaml `status`) gets a
state machine inferred from its value list by keyword, refined per table in
config/advsim/lifecycles.yaml.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rng import Rand
from .schema import Schema

FUTURE = re.compile(r"^(draft|pending|planned|scheduled|submitted|proposed|prospect|not_started|upcoming|new|"
                    r"briefing|planning|pending_\w+|testing|training|requested|received|not_trafficked|"
                    r"not_assigned|unreconciled|open)$", re.I)
CURRENT = re.compile(r"^(active|in_progress|live|running|in_flight|on_track|in_execution|in_production|"
                     r"trafficked|approved|on_pace|in_review|delivering|issued|sent|executing|locked|"
                     r"partially_\w+|ahead|behind|at_risk|matched|scheduled)$", re.I)
PAST = re.compile(r"^(completed?|closed|paid|expired|archived|terminated|achieved|reconciled|cleared|"
                  r"finali[sz]ed|inactive|churned|lapsed|delivered|superseded|fully_\w+|retired|deprecated|"
                  r"final|renewed|executed|confirmed|resolved|recognized)$", re.I)
NEGATIVE = re.compile(r"(cancel|reject|fail|suspend|disput|hold|paus|block|miss|fraud|written_off|defer|"
                      r"revers|dormant|under_deliver|over_deliver|over_budget|escalat|discrepan|revision|"
                      r"reassign|probation|disqualif|error|excluded|suppressed|terminated)", re.I)
PHASES = ("future", "current", "past")


@dataclass
class Machine:
    table: str
    column: str
    values: list[str]
    phases: dict[str, dict[str, float]] = field(default_factory=dict)
    transitions: dict[str, list[str]] = field(default_factory=dict)
    dwell_hours: dict[str, float] = field(default_factory=dict)

    def terminal(self, value: str) -> bool:
        return not self.transitions.get(value)


def classify(value: str) -> str:
    if NEGATIVE.search(value):
        return "negative"
    for name, rx in (("past", PAST), ("current", CURRENT), ("future", FUTURE)):
        if rx.match(value):
            return name
    return "current"


def infer(table: str, column: str, values: list[str]) -> Machine:
    kinds = {v: classify(v) for v in values}
    m = Machine(table, column, values)
    for ph in PHASES:
        own = [v for v in values if kinds[v] == ph]
        neg = [v for v in values if kinds[v] == "negative"]
        w = {v: 1.0 / (i + 1) ** 0.5 for i, v in enumerate(own)}
        for v in neg:
            w[v] = 0.04 if ph != "past" else 0.07
        if not own:
            w[values[0] if ph == "future" else values[-1] if ph == "past" else values[min(1, len(values) - 1)]] = 1.0
        m.phases[ph] = w
    rank = {"future": 0, "current": 1, "past": 2}
    for v in values:
        k = kinds[v]
        if k == "negative":
            back = [x for x in values if kinds[x] == "current"]
            m.transitions[v] = back[:1] if re.search(r"paus|hold|block|suspend|revision", v) else []
            continue
        if k == "past":
            m.transitions[v] = []
            continue
        nxt = [x for x in values if kinds[x] != "negative" and rank[kinds[x]] == rank[k] + 1]
        later_same = [x for x in values[values.index(v) + 1:] if kinds[x] == k]
        m.transitions[v] = (later_same[:1] + nxt[:1]) or nxt
        m.transitions[v] += [x for x in values if kinds[x] == "negative"][:1]
    m.dwell_hours = {v: 72.0 for v in values}
    return m


class Lifecycles:
    def __init__(self, schema: Schema, overrides: dict) -> None:
        self.machines: dict[str, Machine] = {}
        for table, column in schema.status_col.items():
            values = schema.code_values(table, column)
            if not values:
                continue
            m = infer(table, column, values)
            o = (overrides or {}).get(table) or {}
            if o.get("phases"):
                m.phases.update({k: dict(v) for k, v in o["phases"].items()})
            if o.get("transitions"):
                m.transitions.update({k: list(v) for k, v in o["transitions"].items()})
            if o.get("dwell_hours"):
                default = o["dwell_hours"].get("default")
                if default:
                    m.dwell_hours = {v: float(default) for v in values}
                m.dwell_hours.update({k: float(v) for k, v in o["dwell_hours"].items() if k != "default"})
            bad = {s for w in m.phases.values() for s in w} | {s for t in m.transitions.values() for s in t}
            bad |= set(m.transitions)
            if bad - set(values):
                raise ValueError(f"lifecycles.yaml {table}: unknown status values {sorted(bad - set(values))}")
            self.machines[table] = m

    def status(self, table: str, phase: str, rnd: Rand) -> str | None:
        m = self.machines.get(table)
        return rnd.weighted(m.phases[phase]) if m else None

    def next(self, table: str, current: str, rnd: Rand) -> str | None:
        m = self.machines.get(table)
        if not m or not m.transitions.get(current):
            return None
        opts = m.transitions[current]
        # mostly the "happy path" (first option); negatives are rare
        return rnd.weighted(opts, [1.0 if i == 0 else 0.03 for i in range(len(opts))])


def phase_of(start, end, today) -> str:
    """future / current / past for a row with (optional) start and end dates."""
    if start and start > today:
        return "future"
    if end and end < today:
        return "past"
    return "current"
