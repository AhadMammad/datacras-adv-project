"""In-memory row store shared by all generators: ids, affinity lookups and unique-value tracking.

Rows are plain dicts keyed by column name. Keys starting with "_" are simulator metadata
(never written to the database), for example "_adv" = owning advertiser id, used to keep
references coherent (a campaign of advertiser A only points at A's brands, agreements...).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .rng import Rand

AFFINITY = ("_adv", "_campaign")


class Registry:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.by_id: dict[str, dict] = {}
        self.pk: dict[str, str] = {}
        self.index: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(list))
        self.used: dict[tuple[str, str], set] = defaultdict(set)
        self.new_rows: dict[str, list[dict]] = defaultdict(list)  # added since the last flush (stream mode)

    def add(self, table: str, pk: str, row: dict) -> dict:
        self.pk[table] = pk
        self.rows[table].append(row)
        self.by_id[row[pk]] = row
        for key in AFFINITY:
            self.index[(table, key)][row.get(key)].append(row)
        self.new_rows[table].append(row)
        return row

    def remove(self, table: str, row: dict) -> None:
        self.rows[table].remove(row)
        self.by_id.pop(row[self.pk[table]], None)
        for key in AFFINITY:
            bucket = self.index[(table, key)].get(row.get(key))
            if bucket and row in bucket:
                bucket.remove(row)

    def take_new(self) -> dict[str, list[dict]]:
        out, self.new_rows = self.new_rows, defaultdict(list)
        return out

    def get(self, row_id) -> dict | None:
        return self.by_id.get(row_id)

    def count(self, table: str) -> int:
        return len(self.rows.get(table, ()))

    def ids(self, table: str) -> list:
        pk = self.pk.get(table)
        return [r[pk] for r in self.rows.get(table, ())] if pk else []

    def pick(self, table: str, rnd: Rand, affinity: dict | None = None, where=None) -> dict | None:
        """Random row of `table`, preferring rows that share the caller's advertiser/campaign."""
        if not self.rows.get(table):
            return None
        pools: list[Iterable[dict]] = []
        for key in AFFINITY:
            val = (affinity or {}).get(key)
            if val is not None:
                pools.append(self.index[(table, key)].get(val, ()))
        pools.append(self.index[(table, "_adv")].get(None, ()))  # shared rows (suppliers, taxonomy...)
        pools.append(self.rows[table])
        for pool in pools:
            cands = [r for r in pool if where is None or where(r)]
            if cands:
                return rnd.choice(cands)
        return None

    def claim(self, table: str, column: str, value) -> bool:
        """Reserve a unique value; False if already taken."""
        s = self.used[(table, column)]
        if value in s:
            return False
        s.add(value)
        return True
