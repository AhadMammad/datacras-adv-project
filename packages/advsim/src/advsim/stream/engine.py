"""Continuous simulation: wall-clock ticks that insert events, move lifecycles, add masters and delete rows.

--speed multiplies how much happens per second (event volume, lifecycle dwell times, new
masters, deletes). Every timestamp stays wall-clock "now", which keeps audit.set_updated()
and CDC consistent.
"""
from __future__ import annotations

import signal
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from psycopg import errors, sql

from .. import dq
from ..config import Settings
from ..lifecycle import classify, phase_of
from ..rng import UTC, Rand
from ..scenarios import campaigns, clients, delivery, finance, supply
from ..scenarios.delivery import HOURS, VIDEO_KINDS, Day, EventWriter
from ..schema import Schema
from ..sink.postgres import PgSink
from ..world import LineItem, World, month_end
from .hydrate import hydrate

LIVE = ("delivering", "under_delivering", "over_delivering")
EVENT_TABLES = ("impression_event", "click_event", "conversion_event", "video_completion_event",
                "viewability_measurement", "delivery_pacing")


class Engine:
    def __init__(self, settings: Settings, schema: Schema, sink: PgSink, speed: float, seed: int) -> None:
        now = datetime.now(UTC)
        self.s = schema
        self.sink = sink
        self.speed = max(0.01, speed)
        self.cfg = settings.profile
        self.rnd = Rand(seed, "stream")
        self.w = World(settings, schema, now.date() - timedelta(days=60), now.date(), seed)
        self.w.now = now
        self.w.fill.live = True
        self.w.seq_floor = 500_000 + self.rnd.int(0, 300_000)
        self.writer = EventWriter(self.w, self.rnd)
        self.noise = dq.Noise(settings.dq, self.rnd)
        self.sample = self.writer.sample
        self.tick_s = float(self.cfg.get_path("stream.tick_seconds", 1.0))
        self.hour_acc: dict = defaultdict(lambda: [0.0, 0, 0, 0, 0, 0, 0])  # li -> spend, imps, clicks, conv, viewable, measurable, vcomp
        self.recent: dict = defaultdict(list)    # li -> recent impression/click rows for conversions
        self.billed: set = set()
        self.stats = defaultdict(int)
        self.stop = False
        self.hour = now.replace(minute=0, second=0, microsecond=0)

    # ------------------------------------------------------------ main loop
    def run(self, duration: float | None) -> None:
        hydrate(self.w, self.sink, int(self.cfg.get("seed", 42)))
        self.baseline()
        self.partitions()
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "stop", True))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop", True))
        t_end = time.monotonic() + duration if duration else None
        last_report = time.monotonic()
        print(f"streaming at speed x{self.speed:g}; {len(self.active())} live line items. Ctrl-C to stop.", flush=True)
        try:
            while not self.stop and (t_end is None or time.monotonic() < t_end):
                t0 = time.monotonic()
                self.tick(datetime.now(UTC), self.tick_s)
                if time.monotonic() - last_report >= 10:
                    self.report()
                    last_report = time.monotonic()
                time.sleep(max(0.0, self.tick_s - (time.monotonic() - t0)))
        finally:
            self.close_hour(datetime.now(UTC))
            self.flush()
            self.report()
            self.sink.close()

    def tick(self, now: datetime, dt: float) -> None:
        w = self.w
        w.now, w.today = now, now.date()
        if now >= self.hour + timedelta(hours=1):
            self.close_hour(now)
            self.hour = now.replace(minute=0, second=0, microsecond=0)
            self.hourly(now)
        out = {t: [] for t in EVENT_TABLES}
        self.events(now, dt, out)
        self.noise.apply(out)
        for table, rows in out.items():
            self.stats[table] += self.sink.copy_dicts(table, rows)
        self.sink.commit("adserver_db")
        self.lifecycle(now, dt)
        self.new_masters(dt)
        self.deletes(dt)
        self.flush()

    def report(self) -> None:
        parts = [f"{k}={v:,}" for k, v in sorted(self.stats.items())]
        print(f"[{datetime.now():%H:%M:%S}] " + " ".join(parts), flush=True)

    # ------------------------------------------------------------ events
    def active(self) -> list[LineItem]:
        today = self.w.today
        return [li for c in self.w.campaigns if c.status == "active" for li in c.line_items
                if li.start <= today <= li.end and li.row["delivery_status"] in LIVE]

    def events(self, now: datetime, dt: float, out: dict) -> None:
        rnd = self.rnd
        weekday = self.cfg.get_path("delivery.weekday_factor", [1] * 7)
        share = HOURS[now.hour] / sum(HOURS) / 3600 * dt * self.speed
        cvr = float(self.cfg.get_path("delivery.cvr", 0.025))
        for li in self.active():
            days = (li.end - li.start).days + 1
            bias = {"under_delivering": 0.72, "over_delivering": 1.08}.get(li.row["delivery_status"], 1.0)
            real = li.budget / days / li.cpm * 1000 * weekday[now.weekday()] * bias * share
            n_imp = rnd.poisson(real / self.sample)
            if not n_imp:
                continue
            s = self.writer.static(li)
            ctr = float(self.cfg.get_path(f"delivery.ctr.{li.kind}", 0.001))
            acc = self.hour_acc[li.id]
            for _ in range(n_imp):
                ts = now - timedelta(seconds=rnd.uniform(0, dt))
                imp = self.writer.impression(li, ts, s)
                out["impression_event"].append(imp)
                if li.kind in VIDEO_KINDS:
                    v = self.writer.video(li, imp, s)
                    v["event_timestamp"] = min(v["event_timestamp"], now)
                    out["video_completion_event"].append(v)
                    acc[6] += self.sample if v["completion_quartile"] == "complete" else 0
                if rnd.chance(ctr):
                    clk = self.writer.click(li, imp, s)
                    clk["click_timestamp"] = min(clk["click_timestamp"], now)
                    out["click_event"].append(clk)
                    self.recent[li.id].append(clk)
                    acc[2] += self.sample
                self.recent[li.id].append(imp)
                acc[4] += self.sample if imp["viewability_status"] == "viewable" else 0
                acc[5] += self.sample if imp["viewability_status"] != "not_measured" else 0
            acc[0] += n_imp * self.sample * li.cpm / 1000
            acc[1] += n_imp * self.sample
            self.recent[li.id] = self.recent[li.id][-200:]
            if self.recent[li.id] and rnd.chance(min(1.0, n_imp * ctr * cvr * 20)):
                src = rnd.choice(self.recent[li.id])
                conv = self.writer.conversion(li, src, s, "click_through" if "click_event_id" in src else "view_through")
                conv["conversion_timestamp"] = now
                conv["created_at"] = conv["updated_at"] = now + timedelta(seconds=rnd.int(1, 30))
                out["conversion_event"].append(conv)
                acc[3] += self.sample

    def baseline(self) -> None:
        """Cumulative delivery so far per live line item (from the latest pacing snapshot)."""
        ids = [li.id for c in self.w.campaigns for li in c.line_items]
        if not ids:
            return
        rows = self.sink.fetch("adserver_db", sql.SQL(
            "SELECT DISTINCT ON (line_item_id) line_item_id, actual_spend_amount, actual_impressions, conversion_count, "
            "click_through_rate FROM performance.delivery_pacing WHERE line_item_id = ANY(%s) "
            "ORDER BY line_item_id, measurement_timestamp DESC"), (ids,))
        base = {r[0]: r for r in rows}
        for c in self.w.campaigns:
            for li in c.line_items:
                r = base.get(li.id)
                if r:
                    imps = int(r[2] or 0)
                    li.daily[li.start - timedelta(days=1)] = Day(float(r[1] or 0), imps, int(imps * float(r[4] or 0)),
                                                                 int(r[3] or 0), 0, 0, 0)

    def close_hour(self, now: datetime) -> None:
        """Write the hour's pacing snapshot and viewability measurement for every line item that delivered."""
        if not self.hour_acc:
            return
        out = {"delivery_pacing": [], "viewability_measurement": []}
        lis = {li.id: li for c in self.w.campaigns for li in c.line_items}
        for li_id, (spend, imps, clicks, conv, viewable, measurable, vcomp) in self.hour_acc.items():
            li = lis.get(li_id)
            if not li or not imps:
                continue
            d = now.date()
            prev = li.daily.get(d) or Day(0, 0, 0, 0, 0, 0, 0)
            hour = Day(spend, imps, clicks, conv, viewable, measurable, vcomp)
            li.daily[d] = Day(prev.spend + spend, prev.impressions + imps, prev.clicks + clicks, prev.conversions + conv,
                              prev.viewable + viewable, prev.measurable + measurable, prev.video_complete + vcomp)
            out["viewability_measurement"].append(self.writer.viewability(li, d, hour, now, self.writer.static(li)))
            out["delivery_pacing"].append(self.writer.pacing(li, d, li.daily[d], now))
        for table, rows in out.items():
            self.stats[table] += self.sink.copy_dicts(table, rows)
        self.sink.commit("adserver_db")
        self.hour_acc.clear()

    # ------------------------------------------------------------ lifecycles
    def lifecycle(self, now: datetime, dt: float) -> None:
        rnd = self.rnd
        n = rnd.poisson(float(self.cfg.get_path("stream.lifecycle_checks_per_minute", 30)) / 60 * dt * self.speed)
        machines = [m for m in self.w.lc.machines.values() if self.w.reg.count(m.table)]
        out_of_order = float(self.w.dq.get("out_of_order_updates") or 0)
        for _ in range(n):
            m = rnd.weighted(machines, [min(self.w.reg.count(x.table), 2000) for x in machines])
            t = self.s.table(m.table)
            rows = self.w.reg.rows[m.table]
            for row in (rnd.choice(rows) for _ in range(25)):
                cur = row.get(m.column)
                if cur is None:
                    continue
                if out_of_order and rnd.chance(out_of_order):
                    back = [v for v, nxt in m.transitions.items() if cur in nxt]
                    if back:
                        self.update(t, row, {m.column: rnd.choice(back)}, now)
                        break
                if m.terminal(cur):
                    continue
                start, end = (row.get(t.date_pairs[0][0]), row.get(t.date_pairs[0][1])) if t.date_pairs else (None, None)
                phase = phase_of(as_date(start), as_date(end), now.date())
                overdue = phase == "past" and classify(cur) in ("future", "current")
                age_h = (now - (row.get("updated_at") or now)).total_seconds() / 3600 * self.speed
                if not overdue and age_h < m.dwell_hours.get(cur, 72):
                    continue
                nxt = self.w.lc.next(m.table, cur, rnd)
                if nxt is None:
                    continue
                kind = classify(nxt)
                if (kind == "current" and phase == "future") or (kind == "past" and phase != "past"):
                    continue
                self.update(t, row, {m.column: nxt, **self.side_effects(m.table, row, nxt, now)}, now)
                break

    def side_effects(self, table: str, row: dict, status: str, now: datetime) -> dict:
        today = now.date()
        if table == "client_invoice" and status == "paid":
            finance.payment(self.w, "inbound", float(row["total_amount"] or 0), today, self.w.ctx(today), self.rnd,
                            client_invoice_id=row["client_invoice_id"], payer_name="Client", payee_name="Agency Holdings US")
            return {"amount_paid": row["total_amount"], "amount_outstanding": 0, "payment_received_date": today}
        if table == "vendor_payable" and status == "paid":
            finance.payment(self.w, "outbound", float(row["net_amount"] or 0), today, self.w.ctx(today), self.rnd,
                            vendor_payable_id=row["vendor_payable_id"], invoice_id=row.get("vendor_invoice_id"),
                            supplier_id=row.get("supplier_id"), payer_name="Agency Holdings US", payee_name="Vendor")
            return {"payment_date": today}
        if table == "campaign":
            for c in self.w.campaigns:
                if c.id == row["campaign_id"]:
                    c.status = status
        return {}

    def update(self, t, row: dict, changes: dict, now: datetime) -> None:
        db = self.s.db_of[t.name]
        sets = sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in changes)
        conn = self.sink.conn(db)
        conn.execute("SELECT set_config('app.actor', %s, true)", ("advsim.workflow",))
        conn.execute(sql.SQL("UPDATE {} SET {} WHERE {} = %s").format(
            sql.Identifier(t.schema, t.name), sets, sql.Identifier(t.pk.name)), [*changes.values(), row[t.pk.name]])
        conn.commit()
        row.update(changes)
        row["updated_at"] = now
        self.stats["updates"] += 1

    # ------------------------------------------------------------ new masters, deletes
    def new_masters(self, dt: float) -> None:
        rnd, w = self.rnd, self.w
        per = dt * self.speed / 86400
        for _ in range(rnd.poisson(float(self.cfg.get_path("stream.new_advertisers_per_day", 0.2)) * per)):
            clients.new_advertiser(w, rnd, None, w.today)
            self.stats["new_advertisers"] += 1
        for _ in range(rnd.poisson(float(self.cfg.get_path("stream.new_suppliers_per_day", 0.1)) * per)):
            supply.add_publisher(w, rnd, len(w.supply))
            self.stats["new_suppliers"] += 1
        for _ in range(rnd.poisson(float(self.cfg.get_path("stream.new_campaigns_per_day", 1.5)) * per)):
            advs = [a for a in w.advertisers if not a.churned and a.brands and a.msa]
            if not advs:
                break
            lead = rnd.int(*self.cfg.get_path("campaigns.lead_days", [14, 45]))
            camp = campaigns.create(w, rnd.choice(advs), w.today + timedelta(days=lead), rnd, brief_date=w.today)
            if camp:
                self.stats["new_campaigns"] += 1

    def deletes(self, dt: float) -> None:
        rnd = self.rnd
        n = rnd.poisson(float(self.cfg.get_path("stream.delete_rate_per_hour", 6)) / 3600 * dt * self.speed)
        rules = self.cfg.get_path("stream.deletable", {}) or {}
        for _ in range(n):
            if not rules:
                return
            table = rnd.choice(list(rules))
            rule = rules[table] or {}
            rows = self.w.reg.rows.get(table) or []
            if rule.get("column"):
                rows = [r for r in rows[-5000:] if r.get(rule["column"]) in set(rule.get("values") or [])]
            if not rows:
                continue
            row = rnd.choice(rows)
            t = self.s.table(table)
            db = self.s.db_of[table]
            conn = self.sink.conn(db)
            try:
                conn.execute(sql.SQL("DELETE FROM {} WHERE {} = %s").format(
                    sql.Identifier(t.schema, t.name), sql.Identifier(t.pk.name)), [row[t.pk.name]])
                conn.commit()
                self.w.reg.remove(table, row)
                self.stats["deletes"] += 1
            except errors.ForeignKeyViolation:
                conn.rollback()

    def flush(self) -> None:
        new = self.w.reg.take_new()
        if not new:
            return
        for db in self.s.systems:
            order, _ = self.s.load_plan(db)
            wrote = False
            for table in order:
                rows = new.get(table)
                if rows:
                    self.stats["inserts"] += self.sink.copy_dicts(table, rows)
                    wrote = True
            if wrote:
                self.sink.commit(db)
        self.w.fill.pending.clear()

    # ------------------------------------------------------------ hourly jobs
    def hourly(self, now: datetime) -> None:
        self.partitions()
        if now.day >= 3:
            self.bill_previous_month(now)

    def partitions(self) -> None:
        from ..backfill import ensure_partitions
        today = self.w.today
        ensure_partitions(self.sink, self.s, today.replace(day=1), (today + timedelta(days=62)))

    def bill_previous_month(self, now: datetime) -> None:
        """Invoice last month's delivery (client and vendor side) once per campaign."""
        first = (now.date().replace(day=1) - timedelta(days=1)).replace(day=1)
        me = month_end(first)
        invoiced = {(r.get("campaign_id"), r.get("billing_period_start_date")) for r in self.w.reg.rows.get("client_invoice", [])}
        lis = [li for c in self.w.campaigns for li in c.line_items if li.start <= me and li.end >= first]
        if not lis:
            return
        rows = self.sink.fetch("adserver_db", sql.SQL(
            "SELECT line_item_id, max(actual_spend_amount) FILTER (WHERE measurement_timestamp < %s) - "
            "coalesce(max(actual_spend_amount) FILTER (WHERE measurement_timestamp < %s), 0), "
            "max(actual_impressions) FILTER (WHERE measurement_timestamp < %s) - "
            "coalesce(max(actual_impressions) FILTER (WHERE measurement_timestamp < %s), 0) "
            "FROM performance.delivery_pacing WHERE line_item_id = ANY(%s) GROUP BY line_item_id"),
            (me + timedelta(days=1), first, me + timedelta(days=1), first, [li.id for li in lis]))
        month = {r[0]: (float(r[1] or 0), int(r[2] or 0)) for r in rows}
        for camp in self.w.campaigns:
            if (camp.id, first) in invoiced or (camp.id, first) in self.billed:
                continue
            items = []
            for li in camp.line_items:
                spend, imps = month.get(li.id, (0.0, 0))
                if spend > 0:
                    days = (min(me, li.end) - max(first, li.start)).days + 1
                    items.append((li, [Day(spend / days, imps // days, 0, 0, 0, 0, 0)] * days))
            self.billed.add((camp.id, first))
            if not items:
                continue
            ctx = self.w.adv_ctx(camp.adv, now.date(), entities={"campaign": camp.id, "brand": camp.brand["brand_id"],
                                                                "contract_insertion_order": camp.client_io["contract_insertion_order_id"]})
            subtotal = sum(sum(d.spend for d in days) for _, days in items)
            finance.client_invoice(self.w, camp, first, me, now.date(), subtotal, items,
                                   camp.adv.row.get("credit_terms") or "net_30", ctx, self.rnd)
            finance.vendor_side(self.w, camp, first, me, now.date(), items, ctx, self.rnd)
            self.stats["invoices"] += 1


def as_date(v):
    if isinstance(v, datetime):
        return v.date()
    return v
