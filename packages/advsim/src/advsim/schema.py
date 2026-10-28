"""Simulation view of the advgen model: tables by name, load order, cycles, status columns."""
from __future__ import annotations

import re
from functools import cached_property
from graphlib import CycleError, TopologicalSorter

from advgen.build import build_model, load_yaml
from advgen.model import Column, Model, System, Table

INT_MAX = 2**31 - 1
BIGINT_MAX = 2**63 - 1
NUMERIC_RE = re.compile(r"numeric\((\d+),(\d+)\)")

# Reference columns that name a *different* row of the target than the one in context
# (hierarchies, replacements, revisions). They are never filled from the context entity.
NON_CONTEXT_REF = re.compile(
    r"(^|_)(parent|child|original|superseded|supersed|replacement|replaced|revised|reassigned|replanned|"
    r"adjusted|predecessor|revision_of|tertiary|seed|root|lookalike_seed|activation_platform)(_|$)")


def numeric_bounds(pg_type: str) -> tuple[float, int] | None:
    """(max absolute value, scale) for numeric/integer types, None otherwise."""
    if m := NUMERIC_RE.fullmatch(pg_type):
        p, s = int(m.group(1)), int(m.group(2))
        return 10 ** (p - s) - 10 ** -s, s
    if pg_type == "integer":
        return INT_MAX, 0
    if pg_type == "bigint":
        return BIGINT_MAX, 0
    return None


class Schema:
    def __init__(self, model: Model | None = None) -> None:
        self.model = model or build_model()
        self.tables: dict[str, Table] = {t.name: t for t in self.model.tables.values()}
        self.systems: dict[str, System] = {s.database: s for s in self.model.systems.values()}
        self.db_of: dict[str, str] = {t.name: self.model.systems[t.system].database for t in self.tables.values()}
        rules = load_yaml("table_rules.yaml")
        self.status_col: dict[str, str] = {
            key.split(".")[1]: r["status"] for key, r in rules.items() if r and r.get("status")}

    # ------------------------------------------------------------ lookups
    def table(self, name: str) -> Table:
        return self.tables[name]

    def system_of(self, table: str) -> System:
        return self.systems[self.db_of[table]]

    def code_values(self, table: str, column: str) -> list[str]:
        t = self.tables[table]
        c = t.col(column)
        if c.code_set:
            return list(self.system_of(table).code_sets[c.code_set].values)
        for ch in c.checks:
            if ch.kind == "in":
                return list(ch.values)
        return []

    def data_columns(self, table: str) -> list[Column]:
        """Columns the simulator writes (everything except audit columns)."""
        return [c for c in self.tables[table].columns if not c.is_audit]

    @cached_property
    def inbound_enforced(self) -> dict[str, list[tuple[str, str]]]:
        """table -> [(referencing table, column)] for enforced FKs (decides what can be deleted)."""
        out: dict[str, list[tuple[str, str]]] = {n: [] for n in self.tables}
        for t in self.tables.values():
            for c in t.columns:
                if c.ref and c.ref.enforced:
                    out[c.ref.target_table].append((t.name, c.name))
        return out

    # ------------------------------------------------------------ load order
    def load_plan(self, database: str) -> tuple[list[str], dict[str, list[str]]]:
        """Insert order for one database and the FK columns that must be loaded NULL then patched.

        Self references are fine inside one COPY (RI checks fire at end of statement), so only
        cross-table cycles need deferring; those edges are always on nullable columns."""
        names = [t.name for t in self.systems[database].tables]
        edges: dict[str, dict[str, list[Column]]] = {n: {} for n in names}
        for n in names:
            for c in self.tables[n].columns:
                if c.ref and c.ref.enforced and c.ref.target_table != n:
                    edges[n].setdefault(c.ref.target_table, []).append(c)
        deferred: dict[str, list[str]] = {}
        while True:
            graph = {n: set(edges[n]) for n in names}
            try:
                return list(TopologicalSorter(graph).static_order()), deferred
            except CycleError as e:
                cycle = e.args[1]  # [a, b, ..., a] where each depends on the next
                for a, b in zip(cycle, cycle[1:]):
                    cols = edges[a].get(b, [])
                    if cols and all(c.nullable for c in cols):
                        deferred.setdefault(a, []).extend(c.name for c in cols)
                        del edges[a][b]
                        break
                else:
                    raise RuntimeError(f"unbreakable FK cycle in {database}: {cycle}")
