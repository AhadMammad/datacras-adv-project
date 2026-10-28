"""Cross-database consistency report: soft references resolve, tables are populated, dates are sane."""
from __future__ import annotations

import csv
from collections import defaultdict

from advgen.build import ROOT
from psycopg import sql

from .schema import Schema
from .sink.postgres import PgSink

SOFT_REFS = ROOT / "mapping" / "cross_system_refs.csv"
SAMPLE = 5000  # rows checked per soft-reference column


def run(schema: Schema, sink: PgSink, orphan_tolerance: float = 0.0) -> bool:
    ok = True
    empty = []
    for db in schema.systems:
        for name, n in sink.counts(db).items():
            if n == 0:
                empty.append(f"{db}.{name}")
    print(f"tables: {95 - len(empty)}/95 populated" + (f"; empty: {', '.join(empty)}" if empty else ""))
    ok &= not empty

    ids: dict[tuple[str, str], set] = {}

    def target_ids(db: str, fqn: str, col: str) -> set:
        key = (db, fqn)
        if key not in ids:
            s, t = fqn.split(".")
            rows = sink.fetch(db, sql.SQL("SELECT {} FROM {}").format(sql.Identifier(col), sql.Identifier(s, t)))
            ids[key] = {r[0] for r in rows}
        return ids[key]

    worst = []
    checked = orphans = 0
    by_db = defaultdict(int)
    with SOFT_REFS.open() as f:
        refs = list(csv.DictReader(f))
    for r in refs:
        s, t = r["from_table"].split(".")
        vals = sink.fetch(r["from_database"], sql.SQL("SELECT {c} FROM {t} WHERE {c} IS NOT NULL LIMIT {n}").format(
            c=sql.Identifier(r["from_column"]), t=sql.Identifier(s, t), n=sql.Literal(SAMPLE)))
        if not vals:
            continue
        known = target_ids(r["to_database"], r["to_table"], r["to_column"])
        bad = sum(1 for (v,) in vals if v not in known)
        checked += len(vals)
        orphans += bad
        if bad:
            by_db[r["from_database"]] += bad
            worst.append((bad / len(vals), bad, f"{r['from_database']}.{r['from_table']}.{r['from_column']} -> {r['to_database']}.{r['to_table']}"))
    rate = orphans / checked if checked else 0
    print(f"soft references: {checked:,} values checked across {len(refs)} columns, {orphans:,} orphans ({rate:.3%})")
    for share, bad, label in sorted(worst, reverse=True)[:10]:
        print(f"   {bad:>7,} ({share:.1%})  {label}")
    ok &= rate <= orphan_tolerance

    checks = [  # (db, label, query returning one integer that must be 0)
        ("erp_db", "client invoices whose lines do not sum to the subtotal",
         "SELECT count(*) FROM (SELECT i.client_invoice_id FROM finance.client_invoice i "
         "JOIN finance.invoice_line l USING (client_invoice_id) GROUP BY i.client_invoice_id, i.subtotal_amount "
         "HAVING abs(sum(l.line_amount) - i.subtotal_amount) > 0.05 * count(*)) x"),
        ("erp_db", "paid client invoices with an outstanding amount",
         "SELECT count(*) FROM finance.client_invoice WHERE invoice_status = 'paid' AND amount_outstanding > 0"),
        ("adserver_db", "clicks earlier than their impression",
         "SELECT count(*) FROM (SELECT 1 FROM performance.click_event c JOIN performance.impression_event i "
         "USING (impression_event_id) WHERE c.click_timestamp < i.impression_timestamp LIMIT 1000) x"),
        ("media_ops_db", "line items outside their flight dates",
         "SELECT count(*) FROM campaign.line_item l JOIN campaign.flight f USING (flight_id) "
         "WHERE l.start_date < f.start_date OR l.end_date > f.end_date"),
    ]
    for db, label, q in checks:
        n = sink.fetch(db, q)[0][0]
        print(f"{'ok  ' if n == 0 else 'FAIL'} {label}: {n}")
        ok &= n == 0
    print("result:", "OK" if ok else "FAILED")
    return ok
