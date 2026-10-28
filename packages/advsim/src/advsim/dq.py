"""Configurable data-quality noise (config/advsim/dq.yaml). Off by default; never breaks constraints.

Event noise (applied per generated day):
  late_events        ingestion_timestamp/created_at pushed hours or days after the event
  duplicate_events   the same event sent twice (new id, identical payload)
  orphan_refs        optional soft references replaced by ids that exist nowhere
Row noise (applied to generated master/transaction rows before loading):
  null_gaps          extra optional columns blanked
  status_regressions status picked from the wrong phase (e.g. "active" for a finished line)
Stream noise:
  out_of_order_updates  status updates that move a row backwards
"""
from __future__ import annotations

from datetime import timedelta

from .rng import Rand

EVENT_TS = {"impression_event": "impression_timestamp", "click_event": "click_timestamp",
            "conversion_event": "conversion_timestamp", "video_completion_event": "event_timestamp"}
ORPHAN_CANDIDATES = ("ad_id", "asset_id", "segment_id", "programmatic_deal_id", "trafficking_instruction_id")


class Noise:
    def __init__(self, cfg: dict, rnd: Rand) -> None:
        self.cfg = cfg or {}
        self.rnd = rnd

    def rate(self, key: str) -> float:
        return float(self.cfg.get(key) or 0.0)

    @property
    def enabled(self) -> bool:
        return any(self.rate(k) > 0 for k in ("late_events", "duplicate_events", "orphan_refs"))

    def apply(self, out: dict[str, list[dict]]) -> None:
        if not self.enabled:
            return
        late, dup, orphan = self.rate("late_events"), self.rate("duplicate_events"), self.rate("orphan_refs")
        max_h = int(self.cfg.get("late_max_hours") or 72)
        rnd = self.rnd
        for table, ts_col in EVENT_TS.items():
            rows = out.get(table) or []
            pk = f"{table}_id"
            extra = []
            for r in rows:
                if late and rnd.chance(late):
                    delay = r[ts_col] + timedelta(hours=rnd.uniform(1, max_h))
                    for c in ("ingestion_timestamp", "created_at", "updated_at"):
                        if c in r:
                            r[c] = delay
                if orphan and rnd.chance(orphan):
                    col = rnd.choice([c for c in ORPHAN_CANDIDATES if r.get(c) is not None] or [None])
                    if col:
                        r[col] = rnd.uuid7()
                if dup and rnd.chance(dup):
                    d = dict(r)
                    d[pk] = rnd.uuid7(r[ts_col])
                    d["created_at"] = d["updated_at"] = r["created_at"] + timedelta(seconds=rnd.int(1, 600))
                    extra.append(d)
            rows.extend(extra)


def degrade_rows(rows_by_table: dict[str, list[dict]], schema, lifecycles, cfg: dict, rnd: Rand) -> None:
    """Row-level noise for backfill masters/transactions (null gaps, status regressions)."""
    gaps = float((cfg or {}).get("null_gaps") or 0)
    regress = float((cfg or {}).get("status_regressions") or 0)
    if not gaps and not regress:
        return
    for table, rows in rows_by_table.items():
        cols = [c.name for c in schema.data_columns(table) if c.nullable and not c.ref and not c.is_pk]
        status = schema.status_col.get(table)
        for r in rows:
            if gaps:
                for c in cols:
                    if r.get(c) is not None and rnd.chance(gaps):
                        r[c] = None
            if regress and status and table in lifecycles.machines and rnd.chance(regress):
                r[status] = lifecycles.status(table, rnd.choice(["future", "current", "past"]), rnd)
